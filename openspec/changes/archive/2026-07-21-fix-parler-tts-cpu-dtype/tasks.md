## 1. Fix dtype condicional em `_ensure_model()`

- [x] 1.1 Substituir `torch_dtype=torch.float16` por `torch_dtype=torch.float32 if device == "cpu" else torch.float16` em `ParlerVoiceGenerator._ensure_model()`
- [x] 1.2 Atualizar o log `expected_weights_mib` para refletir o dtype real (~2456 MB / ~2.4 GB em FP32, ~1228 MB / ~1.2 GB em FP16)

## 2. Delta spec

- [x] 2.1 Sync `specs/generative-voice-design/spec.md` do delta para o spec principal em `openspec/specs/generative-voice-design/spec.md`

## 3. Verificação

- [x] 3.1 Testar geração de voz em CPU (ou simular com `device="cpu"`) para confirmar que o erro de dtype não ocorre mais
