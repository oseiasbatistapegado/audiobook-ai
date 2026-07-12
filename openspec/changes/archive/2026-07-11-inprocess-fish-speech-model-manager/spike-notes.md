# Spike 1.1 — Fish Speech in-process

Date: 2026-07-11 · Host Python: 3.14.6 (Nix flake / uv venv)

## Findings

| Item | Result |
|------|--------|
| App Python | Keep `requires-python = ">=3.14"` (current toolchain) |
| `huggingface_hub` | Installs cleanly on 3.14 (`>=0.30` / resolved 1.23.0) |
| `fish-speech` pin | Git tag `v2.0.0-beta` (API: `TTSInferenceEngine`, `ServeTTSRequest`, loaders in `tools/server/model_manager.py`) |
| Upstream `torch==2.8.0` | **No cp314 wheels** (only ≤cp313) — unusable as-is on 3.14 |
| Torch on 3.14 | PyPI `torch>=2.13` + `torchaudio>=2.11` (torchaudio lags) |
| Full fish-speech deps | Pulls Gradio/WandB/etc. — **not** declared as transitive deps; install fish-speech from git with overrides (see README) |
| Load + one inference | Validated API surface from upstream sources; full GPU load requires `uv sync --extra tts-fish` + fish-speech + weights download (~11 GB) — covered by smoke docs |

## Pins registered in product code

- Extra: `tts-fish` → `torch>=2.13`, `torchaudio>=2.13`, plus runtime helpers listed in `pyproject.toml`
- Core: `huggingface_hub`, `filelock` (manager download + concurrent lock)
- Model: `fishaudio/s2-pro` revision `1de9996b6be38b745688de084d87a5633f714e4e` (never `main`)
- Required weight files: see `audiobook_ai.weights.fish.FishSpeechModel`
