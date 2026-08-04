## REMOVED Requirements

### Requirement: Interface TTSBackend pluggable
**Reason:** Capability `tts-fish-speech` retirada; o ator de produto passa a ser `tts-qwen3`.
**Migration:** Usar requisitos em `tts-qwen3` (factory `qwen3-tts`).

### Requirement: Inferência Fish Speech local sem servidor HTTP
**Reason:** Fish Speech removido do produto.
**Migration:** Síntese via `Qwen3TTSBackend` / worker Qwen3-TTS (`tts-qwen3`).

### Requirement: Load e reuso do modelo dentro do worker
**Reason:** Worker Fish substituído pelo worker TTS Qwen3.
**Migration:** Requisitos equivalentes em `tts-qwen3` e `gpu-lifecycle` (fase `tts`).

### Requirement: Liberação do engine e hard reclaim
**Reason:** Hard reclaim permanece, mas sob worker TTS genérico / Qwen3.
**Migration:** Ver `tts-qwen3` e `gpu-lifecycle`.

### Requirement: Síntese orientada a SpeechChunks no worker
**Reason:** Movido para o ator Qwen3-TTS.
**Migration:** `tts-qwen3` + `speech-chunking` / `chunk-resume`.

### Requirement: Alocador PyTorch com expandable_segments no worker Fish
**Reason:** Renomeado/absorvido pelo worker TTS.
**Migration:** Requisito equivalente em `tts-qwen3` (worker TTS).

### Requirement: Pesos Fish seguem o alias selecionado
**Reason:** Aliases `s1-mini` / `s2-pro` e `--fish-model` removidos.
**Migration:** Logical id `qwen3-tts` no ModelManager (`model-manager` + `tts-qwen3`).
