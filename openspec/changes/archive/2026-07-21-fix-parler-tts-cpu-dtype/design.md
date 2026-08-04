## Context

O Parler-TTS é carregado com `torch_dtype=torch.float16` no `ParlerVoiceGenerator._ensure_model()`. Em GPUs (CUDA/ROCm), FP16 reduz o consumo de VRAM para ~1.2 GB e é compatível com os operadores half-precision do dispositivo.

Em CPU, `from_pretrained(torch_dtype=torch.float16)` converte os pesos (`nn.Parameter`), mas **não converte buffers não-persistentes** registrados com `persistent=False`, como `inv_freq` no `ParlerTTSRotaryEmbedding`. O `forward` do RoPE força `.float()` em um bloco `autocast(enabled=False)`, retornando `cos/sin` em `float32`. Quando esses tensores são usados com hidden states em `float16`, o runtime PyTorch lança:

```
expected m1 and m2 to have the same dtype, but got: c10::Half != float
```

Em CPU, não há aceleração para half-precision, então FP16 oferece zero benefício de performance e apenas introduz bugs de dtype.

## Goals / Non-Goals

**Goals:**
- Eliminar o dtype mismatch em CPU sem alterar o comportamento em GPU
- Manter FP16 em GPU (zero regressão de VRAM)
- Minimizar a superfície de mudança (uma linha + log)

**Non-Goals:**
- Não estamos corrigindo patches do Parler-TTS em `generator.py`
- Não estamos mudando a arquitetura de geração de vozes
- Não estamos alterando o modelo ou checkpoint do Parler-TTS

## Decisions

### Decision 1: dtype condicional por dispositivo, não patch upstream

**Escolha**: Detectar o dispositivo antes de `from_pretrained` e usar `float32` em CPU, `float16` em GPU.

**Alternativas consideradas:**
- **Patch `ParlerTTSRotaryEmbedding.forward`**: Poderíamos forçar o retorno no dtype correto, mas isso acopla o código a internals do Parler-TTS que podem mudar.
- **`model.to(device, dtype)` após load**: `.to()` não converte buffers não-persistentes de forma confiável; além disso, `inv_freq` é float32 propositalmente no RoPE (precisão para long contexts).
- **`torch.autocast` wrapper**: Adicionar autocast ao redor de `generate()` esconde o problema sem resolvê-lo e pode introduzir artefatos de áudio.

**Rationale**: A abordagem mais simples e correta. CPU não precisa de FP16. GPU continua com FP16. Zero acoplamento a internals.

### Decision 2: Log condicional do peso estimado

O log `expected_weights_mib=~1228` é específico de FP16. Em FP32, o modelo ocupa ~2.4 GB. O log será ajustado para refletir o dtype real.

## Risks / Trade-offs

| Risk | Mitigation |
|------|-----------|
| FP32 em CPU consome ~2.4 GB RAM vs 1.2 GB em FP16 | O modelo mini tem ~122M params — 2.4 GB é trivial em RAM moderna |
| `torch.cuda.is_available()` pode ser `False` em ROCm sem CUDA | O código já usa `torch.cuda.is_available()` que funciona em HIP/ROCm via PyTorch-ROCm |

## Migration Plan

- Mudança pontual em `_ensure_model()`. Nenhum rollback necessário.
- Se houver regressão em GPU, reverter a linha do dtype condicional para FP16 fixo.
