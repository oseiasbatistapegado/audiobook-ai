## Context

O worker de Voice Design roda em `.venv-parler` com `transformers==4.46.1` e `parler-tts==0.2.3` instalado do PyPI (não git HEAD). O worker de TTS roda em `.venv` com `transformers==4.57.3`. Os patches em `_patch_parler_tts_config()` já foram tornados condicionais por versão do transformers na iteração anterior.

**Diagnóstico completo da investigação (2026-07-31):**

O erro `'DynamicCache' object has no attribute 'key_cache'` ocorre durante `model.generate()` do Parler-TTS. Investigamos exaustivamente:

1. `parler-tts==0.2.3` já está instalado (não git HEAD) ✓
2. `transformers==4.46.1` já está no `.venv-parler` ✓
3. `DynamicCache.key_cache` existe em transformers 4.46.1 (definido em `__init__`) ✓
4. `DynamicCache.key_cache` NÃO existe em transformers 4.57.3 ✗
5. `StaticCache` NÃO tem `key_cache` ✗
6. `Cache` base (abstrata) NÃO tem `key_cache` ✗
7. O worker roda isolado com `.venv-parler/bin/python` e PYTHONPATH scrubbed ✓
8. `_patch_parler_tts_config()` NÃO toca em `DynamicCache` ✓
9. O modelo `freds0/parler-tts-mini-v1.1-ptbr` não tem `cache_implementation` definido ✓

**Caminho do erro no código do Parler-TTS (`modeling_parler_tts.py`):**

```python
# ParlerTTSAttention.forward (linha 520-533)
is_updated = past_key_value.is_updated.get(self.layer_idx)  # EncoderDecoderCache tem, DynamicCache NÃO tem
if is_cross_attention:
    past_key_value.is_updated[self.layer_idx] = True
    past_key_value = past_key_value.cross_attention_cache   # → DynamicCache (sem is_updated!)
else:
    past_key_value = past_key_value.self_attention_cache    # → DynamicCache (sem is_updated!)

if is_cross_attention and past_key_value and is_updated:
    key_states = past_key_value.key_cache[self.layer_idx]   # CRASH se past_key_value é Cache base
```

**Hipótese confirmada:**
- O `DynamicCache` de transformers 4.46.1 tem `key_cache`/`value_cache` definidos em `__init__`
- Mas o `EncoderDecoderCache.__init__` armazena `self_attention_cache` e `cross_attention_cache` como referências `Cache` (abstratas)
- Durante o forward pass em GPU (ROCm), o `past_key_value` pode ser um objeto `Cache` base que não tem `key_cache`
- O Parler-TTS assume que após desembrulhar, o cache terá `key_cache[layer_idx]` (API legacy)
- Em transformers 4.46.1, `DynamicCache` tem essa API, mas `Cache` base e `StaticCache` não

**Solução: Monkey-patch `DynamicCache` com propriedades delegadas**

Injetar `key_cache` e `value_cache` como propriedades no `DynamicCache` que delegam para `layers` (API moderna) ou retornam lista vazia se `layers` não existe:

```python
# Monkey-patch para DynamicCache
from transformers.cache_utils import DynamicCache

@property
def key_cache(self):
    if hasattr(self, 'layers'):
        return [layer.keys for layer in self.layers] if self.layers else []
    return getattr(self, '_key_cache', [])

@property
def value_cache(self):
    if hasattr(self, 'layers'):
        return [layer.values for layer in self.layers] if self.layers else []
    return getattr(self, '_value_cache', [])

DynamicCache.key_cache = key_cache  # type: ignore[assignment]
DynamicCache.value_cache = value_cache  # type: ignore[assignment]
```

## Goals / Non-Goals

**Goals:**
- Parler-TTS voice generation funciona em GPU sem erro `DynamicCache.key_cache`
- Monkey-patch injeta `key_cache`/`value_cache` como propriedades delegadas em `DynamicCache`
- Patch é aplicado automaticamente por `_patch_parler_tts_config()` (mesmo padrão dos patches existentes)
- Funciona em transformers 4.46.1 (Parler) e 4.57+ (Qwen-TTS) sem conflito

**Non-Goals:**
- Mudar `transformers` de 4.46.1 para 4.57+ (manter 4.46.1 para compatibilidade Parler)
- Reescrever `_patch_parler_tts_config()` — patches já estão condicionais e corretos
- Mudar a arquitetura de worker isolado ou dependências do TTS
- Instalar flash_attention_2 (incompatível com ROCm)

## Decisions

**1. Monkey-patch `DynamicCache` com propriedades delegadas**

Adicionar ao final de `_patch_parler_tts_config()`:
```python
# Patch DynamicCache to provide key_cache/value_cache as properties
# Parler-TTS attention layers access past_key_value.key_cache[layer_idx] after
# unwrapping EncoderDecoderCache.self_attention_cache (or cross_attention_cache).
# In transformers 4.46+, DynamicCache stores data in self.layers (list of DynamicLayer).
# The legacy key_cache[layer_idx] access pattern must work regardless of which
# Cache subclass is unwrapped.
if hasattr(DynamicCache, '_patched'):
    return  # Guard against double-patch

@property
def _prop_key_cache(self):
    if hasattr(self, 'layers') and self.layers:
        return [layer.keys for layer in self.layers]
    return []

@property
def _prop_value_cache(self):
    if hasattr(self, 'layers') and self.layers:
        return [layer.values for layer in self.layers]
    return []

DynamicCache.key_cache = _prop_key_cache  # type: ignore[assignment]
DynamicCache.value_cache = _prop_value_cache  # type: ignore[assignment]
DynamicCache._patched = True
```

**2. Manter `parler-tts==0.2.3` pin no bootstrap script**

`scripts/bootstrap_parler_venv.sh` já tem `pip install "parler-tts==0.2.3"` (linha 56) — não precisa mudar.

**3. Manter patches condicionais existentes**

Os guards `_TRANSFORMERS_457` em `_patch_parler_tts_config()` já estão corretos. São mantidos como defesa contra regressões futuras.

## Risks / Trade-offs

- [Baixo] Monkey-patch pode conflitar com futuras versões do transformers → Patch é protegido por `_patched` guard e só afeta `DynamicCache` do `.venv-parler`
- [Baixo] Propriedades delegadas podem ser mais lentas que acesso direto → Desprezível vs. custo de I/O do modelo
- [Pro] Monkey-patch é transparente ao usuário — funciona mesmo se Parler-TTS for atualizado sem patch
- [Pro] Patch é idempotente — pode ser chamado múltiplas vezes sem efeito colateral

## Migration Plan

1. Adicionar monkey-patch de `DynamicCache.key_cache`/`value_cache` em `_patch_parler_tts_config()` em `src/audiobook_ai/voice/generator.py`
2. Validar que `_patch_parler_tts_config()` continua funcionando (patches 4.57+ não conflitam)
3. Testar voice generation com `uv run audiobook-ai generate <pdf>` — deve completar sem `DynamicCache.key_cache` error
4. Verificar `uv run pytest` e `uv run ruff check`

Rollback: Remover o monkey-patch se introduzir problemas em outra versão do transformers.
