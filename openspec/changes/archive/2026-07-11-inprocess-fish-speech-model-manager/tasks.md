## 1. Spike e dependências

- [x] 1.1 Spike: validar Python mínimo, install uv/pip, load do modelo e uma inferência simples in-process; registrar `requires-python`, extra `tts-fish` e pins (sem deps não usadas)
- [x] 1.2 Adicionar `huggingface_hub` e deps Fish/torch no `pyproject.toml` conforme resultado do spike; documentar install no README
- [x] 1.3 Definir `FishSpeechModel` com `repository` + `revision` pinada (nunca `main`) e lista de arquivos required

## 2. ModelManager (`weights/`)

- [x] 2.1 Criar `weights/` com `manager.py`, `cache.py`, `fish.py`; resolução de cache root na ordem `--cache-dir` > `AUDIOBOOK_AI_CACHE_DIR` > `~/.cache/audiobook-ai/`
- [x] 2.2 Implementar `ensure_model` / `get_model` com download via `huggingface_hub` na revision pinada, callback de progresso e skip se cache íntegro
- [x] 2.3 Validar somente arquivos required (resiliente a extras) + reparo de cache incompleto
- [x] 2.4 Implementar file lock no cache para downloads concorrentes (um baixa, outros aguardam/reutilizam)
- [x] 2.5 Testes unitários: primeira vs segunda chamada, incompleto, lock concorrente, revision não-`main` (hub mockado + `tmp_path`)

## 3. FishSpeechBackend in-process

- [x] 3.1 Reescrever `FishSpeechBackend` para carregar engine via path do manager; remover `httpx`/health/URL
- [x] 3.2 Garantir load único (`warmup`/init) e reuso em múltiplos `synthesize(TTSRequest) -> AudioSegment`
- [x] 3.3 Mapear `voice_id` + emotion para a API in-process; voz default `narrator` / referências mínimas
- [x] 3.4 Erros claros: import ausente, GPU indisponível, pesos inválidos (sem fallback HTTP)
- [x] 3.5 Atualizar factory para backend in-process + manager; registro único `fish-speech`

## 4. Pipeline, CLI e config

- [x] 4.1 Remover `--fish-speech-url` / `FISH_SPEECH_URL` de `cli.py`, `config.py` e `pipeline.py`
- [x] 4.2 Adicionar `--cache-dir` e honor `AUDIOBOOK_AI_CACHE_DIR`; stages `model-ensure` / download / init
- [x] 4.3 Assegurar que o pipeline reutiliza a mesma instância TTS ao longo dos capítulos (LLM Ollama inalterado)

## 5. Testes, docs e limpeza

- [x] 5.1 Atualizar `tests/test_tts.py` (e correlatos) para mocks in-process/manager; remover expectativas HTTP
- [x] 5.2 Atualizar README + `docs/SMOKE.md` para UX 1ª (download) / 2ª (cache) sem `api_server`/compose como pré-requisito do app
- [x] 5.3 Rodar `uv run pytest` e revisar smoke manual documentado (GPU + Ollama + ffmpeg)
