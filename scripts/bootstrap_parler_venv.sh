#!/usr/bin/env bash
# Bootstrap an isolated Parler Voice Design venv (.venv-parler).
# Must NOT share transformers with the main Qwen3-TTS venv (4.57.3).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

VENV="${AUDIOBOOK_AI_PARLER_VENV:-$ROOT/.venv-parler}"
PYTHON_BIN="${AUDIOBOOK_AI_PARLER_BOOTSTRAP_PYTHON:-python3.12}"

echo "Bootstrapping Parler runtime at $VENV"

if [[ ! -d "$VENV" ]]; then
  "$PYTHON_BIN" -m venv "$VENV"
fi

# Avoid Nix/direnv PYTHONPATH leaking into pip resolution.
unset PYTHONPATH PYTHONHOME || true

# shellcheck disable=SC1091
source "$VENV/bin/activate"

python -m pip install -U pip setuptools wheel

# ROCm torch first (same stack as product host when available).
if [[ "${AUDIOBOOK_AI_PARLER_TORCH_INDEX:-}" == "cpu" ]]; then
  pip install "torch>=2.9.0" "torchaudio>=2.9.0"
else
  pip install "torch==2.9.1+rocm6.4" "torchaudio==2.9.1+rocm6.4" \
    --index-url "${AUDIOBOOK_AI_PARLER_TORCH_INDEX:-https://download.pytorch.org/whl/rocm6.4}"
fi

# Parler pin: transformers exactly 4.46.1 (incompatible with qwen-tts 4.57.3).
# Prefer protobuf 4.x for sentencepiece/tokenizers; install DAC with --no-deps
# so descript-audiotools cannot force protobuf<3.20.
pip install \
  "transformers==4.46.1" \
  "sentencepiece>=0.2.0" \
  "soundfile>=0.12.0" \
  "numpy>=1.26.0,<2.3" \
  "protobuf>=4.25.0,<5" \
  "accelerate>=0.33.0,<1.0" \
  "requests>=2.31.0" \
  "charset-normalizer" \
  "idna" \
  "urllib3" \
  "certifi"

pip install --no-deps "descript-audio-codec==1.0.0"
pip install --no-deps "descript-audiotools==0.7.2" || true
# Minimal audiotools runtime peers used by DAC decode (best-effort).
pip install "einops" "julius" "randomname" "flatten-dict" "markdown2" \
  "pyloudnorm" "importlib-resources" "argbind" || true

pip install "parler-tts==0.2.3"

# Also install in the main .venv (editable install pulls it in) so that
# in-process code paths (tests, dev) use the compatible version.
# Must use --no-deps to avoid pulling transformers==4.46.1 into the main venv.
pip install --no-deps "parler-tts==0.2.3"

# Editable install of audiobook_ai so the worker module resolves.
pip install -e "$ROOT" --no-deps
pip install "filelock>=3.13.0" "pydantic>=2.13.4" "rich>=15.0.0" "typer>=0.26.8" \
  "huggingface_hub>=0.34.0,<1.0" "ollama>=0.6.2" "pymupdf>=1.28.0"

python - <<'PY'
import transformers
from parler_tts import ParlerTTSForConditionalGeneration
import dac
print("parler venv OK transformers=", transformers.__version__)
assert transformers.__version__.startswith("4.46.1"), transformers.__version__
print("dac OK", getattr(dac, "__version__", "?"))
PY

echo "Done. Export for generate:"
echo "  export AUDIOBOOK_AI_VOICE_DESIGN_PYTHON=$VENV/bin/python"
