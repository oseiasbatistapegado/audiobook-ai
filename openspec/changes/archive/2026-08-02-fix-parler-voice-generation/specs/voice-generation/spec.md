## ADDED Requirements

### Requirement: DynamicCache resilience for Parler-TTS cache access
`DynamicCache` MUST provide `key_cache` and `value_cache` as property-style accessors that delegate to `self.layers` (the modern cache API in transformers >= 4.46). This monkey-patch MUST be applied unconditionally in `_patch_parler_tts_config()` BEFORE the model is loaded, to make `past_key_value.key_cache[layer_idx]` access resilient regardless of which `Cache` subclass is unwrapped from `EncoderDecoderCache`. The patch MUST be idempotent (guarded by `hasattr(DynamicCache, '_patched')`).

#### Scenario: DynamicCache.key_cache exists after patch
- **WHEN** `_patch_parler_tts_config()` is called in `.venv-parler` with `transformers==4.46.1`
- **THEN** `DynamicCache.key_cache` and `DynamicCache.value_cache` properties exist and return empty list when `layers` is empty

### Requirement: Parler-TTS stable release install
O extra `voice-parler` SHALL declarar `parler-tts==0.2.3` como dependência explícita (não git HEAD). A versão 0.2.3 é a versão estável mínima compatível com `transformers==4.46.1`. O ambiente de Voice Design `.venv-parler` NÃO DEVE instalar `parler-tts` via `pip install --no-deps "parler-tts @ git+..."`.
A implementação primária deve ser o adapter Parler-TTS pt-BR pinado. O extra/dependências de Voice Design devem ser autossuficientes: instalar suporte Parler + suporte Qwen3-TTS **sem** instalar `fish-speech` deve permitir Voice Design funcional. A dependência de decode efetivamente usada pelo runtime Parler pinado deve ser descoberta em ambiente sem Fish, declarada diretamente no extra `voice-parler`, e pinada; NÃO deve permanecer como transitiva implícita via `fish-speech`.

Os patches de compatibilidade em `_patch_parler_tts_config()` devem ser aplicados condicionalmente baseado na versão do `transformers` instalada. Patches específicos para `transformers >= 4.57` (ex. `_adapter_prepare_attn_mask`, `GenerationMixin` MRO injection, `_get_initial_cache_position`) NÃO devem ser aplicados em `transformers < 4.57`. Patches genéricos (ex. `ParlerTTSConfig.__init__`, `AutoConfig.register`) devem ser aplicados independentemente da versão.

O extra `voice-parler` deve declarar explicitamente `transformers==4.46.1` como dependência para evitar drift de versão.

#### Scenario: Parler sem fish-speech
- **WHEN** o ambiente tem extras Parler e Qwen3-TTS instalados e `fish-speech` ausente
- **THEN** o worker/gerador Parler consegue materializar `reference.wav` válido

#### Scenario: Gate composto de remoção do Fish
- **WHEN** `fish-speech` não está instalado, Parler gera `reference.wav`, e Qwen3-TTS clona essa referência com sucesso
- **THEN** o gate de remoção do Fish passa e a dependência DAC/decode está declarada no extra Parler

#### Scenario: Factory resolve gerador generativo
- **WHEN** a configuração default de voice generator está ativa
- **THEN** o factory retorna o gerador Parler, não um gerador Qwen VoiceDesign

#### Scenario: Patches não quebram em transformers 4.46.1
- **WHEN** o worker de voice design roda em `.venv-parler` com `transformers==4.46.1`
- **THEN** `_adapter_prepare_attn_mask` NÃO é aplicado e `model.generate()` usa a assinatura original do transformers 4.46.1 sem `TypeError`

#### Scenario: Patches aplicam-se em transformers 4.57+
- **WHEN** um ambiente usa `transformers >= 4.57`
- **THEN** `_adapter_prepare_attn_mask` e outros patches 4.57+ são aplicados para garantir compatibilidade

#### Scenario: transformers pinado no extra voice-parler
- **WHEN** o extra `voice-parler` é listado em `pyproject.toml`
- **THEN** `transformers==4.46.1` aparece como dependência explícita

#### Scenario: parler-tts instalado de versão estável do PyPI
- **WHEN** `parler-tts` está listado em `pyproject.toml` com versão estável (0.2.3) no extra `voice-parler`
- **THEN** `uv sync --extra voice-parler` instala `parler-tts==0.2.3` do PyPI, não do git HEAD

#### Scenario: Voice Design funciona em GPU
- **WHEN** o worker de voice design roda em `.venv-parler` com `transformers==4.46.1` e `parler-tts==0.2.3` instalado via PyPI
- **THEN** `model.generate()` completa sem erro `DynamicCache.key_cache` em GPU (ROCm/CUDA)
