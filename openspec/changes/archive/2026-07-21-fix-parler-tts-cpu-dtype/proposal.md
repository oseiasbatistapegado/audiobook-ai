# Fix Parler-TTS dtype mismatch on CPU

## Why

O Parler-TTS falha com erro de dtype (`c10::Half != float`) ao rodar em CPU. O modelo é carregado em `torch.float16`, mas buffers não-persistentes (ex. `inv_freq` no `ParlerTTSRotaryEmbedding`) permanecem em `float32`. Em CPU, não há aceleração para half-precision, e o mismatch de dtype propaga até um tensor operation que espera operandos do mesmo tipo. O erro bloqueia completamente a geração de vozes em ambientes sem GPU.

## What Changes

- **Carregamento condicional do dtype**: Substituir `torch_dtype=torch.float16` por um dtype que depende do dispositivo — `float32` em CPU, `float16` em GPU/ROCm.
- **Ajuste do log de peso estimado**: Atualizar o log `expected_weights_mib` para refletir o dtype real usado.
- **Atualizar spec `generative-voice-design`**: Refinar o requisito de FP16 para mencionar que é GPU-only; em CPU o modelo usa FP32.

## Capabilities

### Modified Capabilities

- `generative-voice-design`: O requisito de FP16 se aplica apenas quando o backend roda em GPU. Em CPU, o dtype é `float32` para evitar mismatches com buffers não convertidos.

## Impact

- `src/audiobook_ai/voice/generator.py`: Alteração no `_ensure_model()` do `ParlerVoiceGenerator` — dtype condicional + log.
- `openspec/specs/generative-voice-design/spec.md`: Delta spec para refinar o requisito de FP16.
- Zero impacto em GPU: o comportamento atual (FP16) é mantido.
- Zero impacto de performance em CPU: float32 é o native precision.
