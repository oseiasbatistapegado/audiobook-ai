# narrative-compiler-py / audiobook_ai

CLI MVP: **PDF → Ollama (JSON) → workers GPU (Voice Design + Fish Speech) → M4B**.

O processo da CLI **não** mantém modelos GPU residentes. Voice Design (Parler) e Fish Speech rodam em **workers isolados**; o exit do worker é o hard reclaim de VRAM. A síntese é particionada em `SpeechChunk`s com manifest/resume sob `out/<book_id>/`.

## Requisitos

- Python ≥ 3.14 (app)
- [Ollama](https://ollama.com) local rodando + modelo instalado (default `qwen3:8b`)
- Extra `tts-fish` (PyTorch) + pacote [fish-speech](https://github.com/fishaudio/fish-speech) pinado em `v2.0.0-beta`
- Extra `voice-parler` + `parler-tts` para Voice Design
- GPU usável (alvo de estabilidade: AMD RX 7900 XTX 24 GB / ROCm / Hyprland)
- `ffmpeg` no PATH — via Nix/direnv (`direnv allow` / `flake.nix`)
- Para o default Fish **S1-mini** (gated HF): `hf auth login` + aceite em https://huggingface.co/fishaudio/openaudio-s1-mini

## Setup do app

```bash
direnv allow   # ou: nix develop  — traz ffmpeg e deps de sistema
uv sync --group dev --extra tts-fish --extra voice-parler
uv pip install --no-deps "fish-speech @ git+https://github.com/fishaudio/fish-speech@v2.0.0-beta"
uv pip install --no-deps "parler-tts @ git+https://github.com/huggingface/parler-tts.git"
```

```bash
uv run python -c "import torch; import fish_speech"
uv run audiobook-ai --help
```

Na **primeira** execução de `generate`, o `ModelManager` baixa pesos Fish para `~/.cache/audiobook-ai/fish-s1-mini/` (default) ou `fish-s2-pro/` com `--fish-model s2-pro` (ou `--cache-dir`). Na **segunda**, reutiliza o cache.

## Uso

```bash
uv run audiobook-ai generate livro.pdf
# default: --model qwen3:8b, --fish-model s1-mini
# out/audiobook.m4b ; estado: out/<book_id>/{story,manifest,audio,jobs,logs}/

uv run audiobook-ai generate samples/sample.pdf --output out/sample.m4b

# LLM Ollama + pesos Fish open (espelhos):
uv run audiobook-ai generate livro.pdf --model qwen3.6:27b --fish-model s2-pro

uv run audiobook-ai generate livro.pdf \
  --model qwen3:8b \
  --fish-model s1-mini \
  --output out/meu-livro.m4b \
  --work-dir out \
  --hard-floor-mib 300 \
  --before-chunk-target-mib 768 \
  --fish-before-load-target-mib 8192 \
  --tts-max-chunk-chars 200
```

Aliases `--fish-model`: `s1-mini` (default; chunk 200 / load 8192) | `s2-pro` (preset chunk 80 / load 22528 se você não overridear).

Overrides também via env: `AUDIOBOOK_AI_HARD_FLOOR_MIB`, `AUDIOBOOK_AI_BEFORE_CHUNK_TARGET_MIB`, `AUDIOBOOK_AI_FISH_BEFORE_LOAD_TARGET_MIB`, `AUDIOBOOK_AI_PARLER_BEFORE_LOAD_TARGET_MIB`, `AUDIOBOOK_AI_TTS_MAX_CHUNK_CHARS`, `AUDIOBOOK_AI_FISH_MODEL`.

MP3 só se `--output …/*.mp3`. O path de saída **não** define `book_id` (BLAKE2b-128 do conteúdo do PDF).

## Fish Speech + VRAM

- Sem `api_server` / HTTP `:8080` / API cloud.
- Inferência no **worker** Fish (`python -m audiobook_ai.workers.fish_speech`); load uma vez por invocação; reclaim best-effort entre chunks; restart controlado sob degradação.
- Voice Design: `python -m audiobook_ai.workers.voice_design` → verify release → Fish.
- Logs estruturados `[gpu]` (before_chunk, after_reclaim, worker_exit, release_verified, …).

Vozes: registry `~/.cache/audiobook-ai/voices/<book_id>/`. Override manual: `references/<voice_id>/`.

## Smoke test manual

Ver [docs/SMOKE.md](docs/SMOKE.md) (multi-chunk, resume, estabilidade do compositor).

## Testes

```bash
uv run pytest
```
