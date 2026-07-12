## Why

O repositório ainda não possui um fluxo ponta a ponta que transforme um PDF em audiolivro. Precisamos de um MVP vertical fino — PDF → texto → capítulos → JSON estruturado via Ollama → áudio Fish-Audio S2 **local** → M4B sob `out/` — para validar a arquitetura modular antes de expandir backends, formatos e features ricas.

## What Changes

- Scaffold do pacote `src/audiobook_ai/` (extractors, parser, llm, state, tts, audio, models, utils, `cli.py`, `pipeline.py`).
- Extrator PDF com PyMuPDF e divisão de capítulos por heurísticas / TOC quando disponível.
- Backend LLM Ollama com saída JSON validada por Pydantic (falha → retry, sem texto livre).
- Estado mínimo em `out/story.json` (personagens + `voice_map`).
- Interface pluggable `TTSBackend` com implementação Fish Speech apenas (HTTP para servidor **self-hosted**; sem cloud API).
- Merge de capítulos em um único **M4B** (default) via ffmpeg do devShell Nix; MP3 opcional se pedido.
- CLI Typer + Rich: `audiobook-ai generate livro.pdf --model ... [--output out/…]`.
- Dependências de sistema no `flake.nix` (ffmpeg, portaudio, sox, etc.) + direnv; Fish Speech como processo externo (clone/uv/Docker ROCm).

### Non-goals

- Sem GUI, Web, Desktop ou API HTTP do produto.
- Sem EPUB (PDF only no MVP).
- Sem Kokoro, Piper ou XTTS.
- Sem API cloud Fish Audio.
- Sem música de fundo, SFX, clonagem de voz ad-hoc, OCR, processamento distribuído ou streaming.
- Sem grafo rico de relacionamentos / timeline além do estado mínimo.

## Capabilities

### New Capabilities

- `pdf-extraction`: Extração de texto de PDF e segmentação em capítulos.
- `llm-interpretation`: Interpretação narrativa via Ollama com JSON Pydantic (speaker, emotion, text/dialogues, story_updates mínimos).
- `story-state`: Persistência mínima em `out/story.json` (characters + voice_map) com IDs estáveis de personagem.
- `tts-fish-speech`: Geração de áudio por segmento via Fish-Audio S2 local, atrás da interface `TTSBackend`.
- `audio-merge`: Concatenação de segmentos/capítulos em um único arquivo de saída (**M4B** default; MP3 opcional) com ffmpeg.
- `generate-cli`: Comando CLI `generate` que orquestra o pipeline completo com opções `--model`, `--output`, `--work-dir` (default `out/`) e progresso Rich.

### Modified Capabilities

- (nenhuma — `openspec/specs/` está vazio)

## Impact

- **Código**: criação de `src/audiobook_ai/` e entrypoint CLI; `pyproject.toml` permanece `narrative-compiler-py` como nome do projeto, pacote instalável `audiobook_ai`.
- **Dependências existentes**: PyMuPDF, ollama, pydantic, typer, rich.
- **Novas / externas**: cliente HTTP para Fish Speech local; ffmpeg + libs de áudio no `flake.nix`; servidor/processo Fish-Audio S2 (git + uv/pip ou Docker ROCm) fora do pacote.
- **Sistemas externos**: serviço Ollama local; API server Fish Speech local (`:8080`); ROCm do host se GPU AMD.
- **Artefatos**: tudo sob `out/` (gitignored).
- **Não afeta**: specs existentes (nenhuma), UI, ou outros backends TTS.
