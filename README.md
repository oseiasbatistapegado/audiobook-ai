# narrative-compiler-py / audiobook_ai

CLI MVP: **PDF → llama-server (JSON) → workers GPU (Parler Voice Design + Qwen3-TTS) → M4B**.

O processo da CLI **não** mantém modelos GPU residentes. Voice Design (Parler) e Qwen3-TTS rodam em **workers isolados**; o exit do worker é o hard reclaim de VRAM. A síntese é particionada em `SpeechChunk`s com manifest/resume sob `out/<book_id>/`.

## Requisitos

- Python ≥ 3.12 (app)
- [llama-server](https://github.com/ggml-org/llama.cpp) local rodando + modelo GGUF instalado (default `localweights/Qwen3.6-35B-A3B-MTP-IQ4_XS-GGUF`)
- Extra `tts-qwen` (PyTorch + `qwen-tts`)
- Extra `voice-parler` + `parler-tts` para Voice Design (inclui DAC pinado; **sem** `fish-speech`)
- GPU usável (alvo de estabilidade: AMD RX 7900 XTX 24 GB / ROCm / Hyprland)
- `ffmpeg` no PATH — via Nix/direnv (`direnv allow` / `flake.nix`)

## Setup do app

```bash
direnv allow   # ou: nix develop  — traz ffmpeg e deps de sistema
# 1) PyTorch ROCm no venv principal (TTS / Qwen3-TTS)
uv pip install torch==2.9.1+rocm6.4 torchaudio==2.9.1+rocm6.4 \
  --index-url https://download.pytorch.org/whl/rocm6.4
# 2) Extra TTS (transformers==4.57.3 via qwen-tts)
uv sync --group dev --extra tts-qwen
# 3) Runtime *isolado* Parler (transformers==4.46.1 — incompatível com qwen-tts)
bash scripts/bootstrap_parler_venv.sh
export AUDIOBOOK_AI_VOICE_DESIGN_PYTHON=$PWD/.venv-parler/bin/python
```

```bash
uv run python -c "import torch; import qwen_tts"
.venv-parler/bin/python -c "import transformers; from parler_tts import ParlerTTSForConditionalGeneration; import dac"
uv run audiobook-ai --help
```

Parler e Qwen3-TTS **não** compartilham o mesmo `site-packages`: o contrato entre
fases é só `reference.wav` + `reference.txt` no filesystem.

Na **primeira** execução de `generate`, o `ModelManager` baixa pesos Qwen3-TTS para
`~/.cache/audiobook-ai/qwen3-tts/` (revision pinada). Na **segunda**, reutiliza o cache.

## Uso

```bash
uv run audiobook-ai generate livro.pdf
# default: --model localweights/Qwen3.6-35B-A3B-MTP-IQ4_XS-GGUF, backend=llama-cpp
# out/audiobook.m4b ; estado: out/<book_id>/{story,manifest,audio,jobs,logs}/

uv run audiobook-ai generate samples/sample.pdf --output out/sample.m4b

uv run audiobook-ai generate livro.pdf \
  --model localweights/Qwen3.6-35B-A3B-MTP-IQ4_XS-GGUF \
  --output out/meu-livro.m4b \
  --work-dir out \
  --hard-floor-mib 300 \
  --before-chunk-target-mib 768 \
  --tts-before-load-target-mib 6144 \
  --tts-max-chunk-chars 5000
```

**Override completo** do comando llama-server via env `LLAMACPP_SERVER_CMD`:
```bash
export LLAMACPP_SERVER_CMD="llama-server --port 8081 --model /path/to/model.gguf --jinja --ngl 999 --spec-type draft-mtp --spec-draft-n-max 4"
```

**Importante:** alterar `--tts-max-chunk-chars` / `TTS_MAX_CHUNK_CHARS` muda o
`chunking_fingerprint` e **invalida o resume** da fase TTS (chunks pendentes são
regenerados).

Overrides via env: `AUDIOBOOK_AI_HARD_FLOOR_MIB`, `AUDIOBOOK_AI_BEFORE_CHUNK_TARGET_MIB`,
`AUDIOBOOK_AI_TTS_BEFORE_LOAD_TARGET_MIB`, `AUDIOBOOK_AI_PARLER_BEFORE_LOAD_TARGET_MIB`,
`AUDIOBOOK_AI_TTS_MAX_CHUNK_CHARS`, `AUDIOBOOK_AI_TTS_CHUNKS_PER_WORKER`.

MP3 só se `--output …/*.mp3`. O path de saída **não** define `book_id` (BLAKE2b-128 do conteúdo do PDF).

## Qwen3-TTS + VRAM

- Sem HTTP TTS / API cloud.
- Pipeline: interpretação de todos os capítulos → fase TTS **contínua** (worker residente) → merge.
- Inferência no **worker** TTS; `VoiceClonePrompt` em cache por `voice_id`; batch same-voice via API oficial.
- Restart por `progressive_growth` só sob pressão real (allocated/reserved crescendo ou free perto do hard floor).
- Voice Design: `python -m audiobook_ai.workers.voice_design` → verify release → TTS.
- Emotion permanece no domínio/metadata; o Base **não** recebe `instruct` derivado de Emotion.
- Logs estruturados `[gpu]` (before_chunk, after_reclaim, worker_exit, release_verified, …).

Vozes: registry `~/.cache/audiobook-ai/voices/<book_id>/` (`reference.wav` + `reference.txt`). Override manual: `references/<voice_id>/`.

## Smoke test manual

Ver [docs/SMOKE.md](docs/SMOKE.md) (multi-chunk, resume, estabilidade do compositor).

## Testes

```bash
uv run pytest
```
