## Why

O MVP atual trata Fish Speech como servidor HTTP externo: o usuário precisa clonar o repo, baixar pesos, subir `api_server` e apontar `--fish-speech-url`. Isso impede a UX “só rodar `audiobook-ai generate`” e contradiz o objetivo de um TTS autocontido no processo Python. Precisamos fechar o ciclo de pesos + inferência dentro do app, sem CLI/servidor/download manual.

## What Changes

- Introduzir pacote `weights/` (`manager.py`, `cache.py`, `fish.py`) com `ModelManager` para ensure/download/lock/validação/cache sob `~/.cache/audiobook-ai/` (prioridade `--cache-dir` > `AUDIOBOOK_AI_CACHE_DIR` > default).
- Download automático via API Python do Hugging Face (`huggingface_hub`) com `repository`+`revision` pinados (nunca `main`); **sem** subprocess/CLI/`git`/`curl`.
- Reescrever `FishSpeechBackend` para inferência **in-process** (`TTSInferenceEngine` / APIs oficiais do Fish Speech), carregando o modelo uma vez e reutilizando entre capítulos; LLM (Ollama) permanece separado.
- **BREAKING:** remover o caminho HTTP local (`httpx` → `:8080`), flags `--fish-speech-url` / `FISH_SPEECH_URL`, e a expectativa de servidor externo no MVP TTS.
- UX da CLI: na primeira execução, progresso Rich de download + “Inicializando modelo…”; nas seguintes, reutilizar cache.
- Manter interface `TTSBackend.synthesize(TTSRequest) -> AudioSegment` (não simplificar para `bytes` cru) para emoção/metadados de merge.
- Ollama permanece serviço externo (fora de escopo deste change). Kokoro/XTTS/Piper não implementados — só o contrato do manager + factory preparado.

## Capabilities

### New Capabilities

- `model-manager`: Gerenciamento centralizado de pesos (existência, download HF, progresso, integridade, paths, cache reutilizável) para backends TTS e futuros (kokoro, xtts, whisper).

### Modified Capabilities

- `tts-fish-speech`: De cliente HTTP self-hosted para backend in-process com load único de pesos via `ModelManager`; proibição de subprocess/CLI/HTTP/FastAPI/localhost para TTS.
- `generate-cli`: Progresso de ensure/download/init do modelo; remoção de opções de URL do servidor Fish Speech.

## Impact

- **Código:** `src/audiobook_ai/tts/fish_speech.py`, `factory.py`, `pipeline.py`, `cli.py`, `config.py`; novo módulo `src/audiobook_ai/weights/`; testes TTS deixam de mockar HTTP e passam a mockar engine/manager.
- **Deps:** `huggingface_hub`; stack Fish Speech + PyTorch (extra/grupo opcional ou dependência documentada); possível tensão Python app (≥3.14) vs upstream Fish (tipicamente 3.12) — resolvida no design.
- **Runtime:** GPU (ROCm/CUDA) e VRAM adequados continuam necessários no host; flake não empacota PyTorch ROCm completo — apenas libs de sistema já presentes.
- **Docs:** README/SMOKE deixam de pedir `api_server` / Docker compose ROCm como pré-requisito do app; descrevem cache e primeira execução.
- **Não afeta:** extração PDF, Ollama, merge ffmpeg, EPUB (ainda fora).
