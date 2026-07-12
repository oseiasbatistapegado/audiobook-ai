## 1. Scaffold do pacote

- [x] 1.1 Criar estrutura `src/audiobook_ai/` (extractors, parser, llm, state, tts, audio, models, utils) com `__init__.py`
- [x] 1.2 Adicionar `config.py` com defaults (`DEFAULT_OLLAMA_MODEL=qwen3.6:27b`, `DEFAULT_WORK_DIR=out`, output M4B sob `out/`, hosts locais, emoções, lista de vozes/`reference_id`)
- [x] 1.3 Configurar `pyproject.toml`: pacote `audiobook_ai`, entrypoint `audiobook-ai`, deps extras se necessário (`httpx`)
- [x] 1.4 Configurar logging central (sem `print`) com helpers em `utils/`; arquivos de log sob `out/logs/` se aplicável
- [x] 1.5 Garantir `out/` no `.gitignore` e criação do diretório na primeira geração

## 2. Modelos Pydantic

- [x] 2.1 Definir `Book`, `Chapter`, `Character`, `Dialogue`, `Emotion` (enum), `StoryState`, `StoryUpdates`
- [x] 2.2 Definir `LLMChapterResponse`, `TTSRequest`, `AudioSegment`
- [x] 2.3 Testes unitários de validação (emoção inválida, JSON mínimo válido)

## 3. Extração PDF e parser de capítulos

- [x] 3.1 Implementar interface `TextExtractor` e `PdfExtractor` (PyMuPDF) com erro claro para PDF sem texto
- [x] 3.2 Implementar parser de capítulos (TOC → heurísticas → fallback capítulo único)
- [x] 3.3 Testes com fixtures de texto/TOC mockado

## 4. Estado da história

- [x] 4.1 Implementar load/save de `out/story.json` tipado (`StoryState`; work-dir configurável)
- [x] 4.2 Implementar resolução de personagem por id/alias e atribuição fixa em `voice_map` (ids locais Fish Speech)
- [x] 4.3 Testes de persistência e imutabilidade de voz após primeira atribuição

## 5. LLM Ollama

- [x] 5.1 Criar interface `LLMBackend` e `OllamaBackend` (host/model configuráveis)
- [x] 5.2 Adicionar prompt em `llm/prompts/interpret_chapter.md` (JSON-only, schema descrito)
- [x] 5.3 Implementar parse + `model_validate` + retry único em falha de schema
- [x] 5.4 Testes com mock do cliente Ollama (sucesso, retry, falha final)
- [x] 5.5 Se houver cache de respostas LLM em disco, gravar sob `out/cache/`

## 6. TTS Fish Speech (local)

- [x] 6.1 Criar interface `TTSBackend` e factory `get_tts_backend`
- [x] 6.2 Implementar `FishSpeechBackend` contra API local (`GET /v1/health`, `POST /v1/tts`; default `http://127.0.0.1:8080`); mapear voice_id + emotion → áudio; **sem** cloud API
- [x] 6.3 Testes com HTTP mock (sucesso e servidor indisponível)
- [x] 6.4 Documentar no README/smoke: subir Fish-Audio S2 (uv/pip Python 3.12 ou `compose.rocm.yml`) + pesos `s2-pro` + `tools/api_server.py`

## 7. Merge de áudio

- [x] 7.1 Implementar verificação de `ffmpeg` no PATH e merge com **default M4B**; aceitar `.mp3` só se `--output` pedir
- [x] 7.2 Garantir ordem dos capítulos/segmentos no concat; intermediários em `out/chapters/`
- [x] 7.3 Testes com mock de subprocess/ffmpeg ou fixtures WAV mínimas

## 8. Pipeline e CLI

- [x] 8.1 Implementar `pipeline.run_generate` (Extract → Parse → Interpret → State/TTS → Merge) sequencial; todos os artefatos sob `out/`
- [x] 8.2 Implementar CLI Typer `generate` com `--model`, `--output` (default M4B em `out/`), `--work-dir out`, host Ollama, URL Fish Speech; progresso Rich
- [x] 8.3 Smoke test manual documentado: PDF amostra + Ollama + Fish Speech local + ffmpeg (direnv) → `out/*.m4b`

## 9. Ambiente Nix

- [x] 9.1 Manter `ffmpeg`, `portaudio`, `sox`, `pkg-config`, `libsndfile`, `cmake` no `flake.nix` (deps de sistema para merge + Fish Speech)
- [x] 9.2 Após mudanças no flake: `direnv allow` / `direnv reload` na raiz; confirmar `ffmpeg` no PATH do shell

## 10. Qualidade final

- [x] 10.1 Revisar tipagem, imports absolutos, docstrings públicas e arquivos < ~300 linhas
- [x] 10.2 Garantir que prompts não estão hardcoded e que não há backends Kokoro/Piper/XTTS nem cloud TTS
- [x] 10.3 Rodar suite de testes e corrigir falhas
