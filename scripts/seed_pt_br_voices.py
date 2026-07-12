#!/usr/bin/env python3
"""Offline seed / reproducibility script for packaged pt-BR voice references.

This script is **build-only** and MUST NEVER run on the audiobook hot path.
Prefer Piper ``pt_BR`` or Kokoro BR when available; falls back to espeak-ng
``pt-br`` so contributors can regenerate assets without cloud TTS.

Usage (from repo root)::

    nix-shell -p espeak-ng ffmpeg --run 'uv run python scripts/seed_pt_br_voices.py'
    # or with Piper on PATH:
    uv run python scripts/seed_pt_br_voices.py --engine piper

Generated files land under ``assets/voices/<id>/``:
  - reference.wav
  - reference.lab
  - metadata.json  (language=pt-BR, license, tags)
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

CANONICAL_TEXT = (
    "Olá, este é um exemplo de voz em português do Brasil para o audiolivro."
)

# narrator + 5 character bases (catalog is filesystem-discovered; not a capacity hardcode)
VOICE_SPECS: list[dict[str, object]] = [
    {
        "id": "narrator",
        "role": "narrator",
        "gender": "male",
        "age_range": "adult",
        "espeak_voice": "pt-br",
        "pitch": 40,
        "speed": 140,
        "piper_model_hint": "pt_BR-faber-medium",
    },
    {
        "id": "base_male_adult",
        "role": "character",
        "gender": "male",
        "age_range": "adult",
        "espeak_voice": "pt-br",
        "pitch": 35,
        "speed": 145,
        "piper_model_hint": "pt_BR-faber-medium",
    },
    {
        "id": "base_female_adult",
        "role": "character",
        "gender": "female",
        "age_range": "adult",
        "espeak_voice": "pt-br+f2",
        "pitch": 55,
        "speed": 150,
        "piper_model_hint": "pt_BR-edresson-low",
    },
    {
        "id": "base_male_young",
        "role": "character",
        "gender": "male",
        "age_range": "young",
        "espeak_voice": "pt-br",
        "pitch": 55,
        "speed": 160,
        "piper_model_hint": "pt_BR-faber-medium",
    },
    {
        "id": "base_female_young",
        "role": "character",
        "gender": "female",
        "age_range": "young",
        "espeak_voice": "pt-br+f3",
        "pitch": 65,
        "speed": 165,
        "piper_model_hint": "pt_BR-edresson-low",
    },
    {
        "id": "base_male_elder",
        "role": "character",
        "gender": "male",
        "age_range": "elder",
        "espeak_voice": "pt-br",
        "pitch": 25,
        "speed": 120,
        "piper_model_hint": "pt_BR-faber-medium",
    },
]


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _which(name: str) -> str | None:
    return shutil.which(name)


def _normalize_wav(src: Path, dest: Path) -> None:
    ffmpeg = _which("ffmpeg")
    if ffmpeg is None:
        shutil.copy2(src, dest)
        return
    subprocess.run(
        [
            ffmpeg,
            "-y",
            "-i",
            str(src),
            "-ac",
            "1",
            "-ar",
            "22050",
            "-sample_fmt",
            "s16",
            str(dest),
        ],
        check=True,
        capture_output=True,
    )


def _synthesize_espeak(spec: dict[str, object], wav_out: Path) -> str:
    espeak = _which("espeak-ng") or _which("espeak")
    if espeak is None:
        raise SystemExit("espeak-ng not found on PATH")
    tmp = wav_out.with_suffix(".raw.wav")
    subprocess.run(
        [
            espeak,
            "-v",
            str(spec["espeak_voice"]),
            "-p",
            str(spec["pitch"]),
            "-s",
            str(spec["speed"]),
            "-w",
            str(tmp),
            CANONICAL_TEXT,
        ],
        check=True,
    )
    _normalize_wav(tmp, wav_out)
    tmp.unlink(missing_ok=True)
    return "espeak-ng"


def _synthesize_piper(spec: dict[str, object], wav_out: Path, model: Path | None) -> str:
    piper = _which("piper")
    if piper is None:
        raise SystemExit("piper not found on PATH (install Piper or use --engine espeak)")
    if model is None or not model.is_file():
        raise SystemExit(
            f"Piper model required for {spec['id']}. Pass --piper-model "
            f"(hint: {spec.get('piper_model_hint')})"
        )
    proc = subprocess.run(
        [piper, "--model", str(model), "--output_file", str(wav_out)],
        input=CANONICAL_TEXT.encode("utf-8"),
        check=True,
    )
    _ = proc
    return "piper"


def seed_one(
    spec: dict[str, object],
    *,
    voices_root: Path,
    engine: str,
    piper_model: Path | None,
) -> None:
    voice_id = str(spec["id"])
    directory = voices_root / voice_id
    directory.mkdir(parents=True, exist_ok=True)
    wav_path = directory / "reference.wav"
    lab_path = directory / "reference.lab"
    lab_path.write_text(CANONICAL_TEXT + "\n", encoding="utf-8")

    if engine == "piper":
        generator = _synthesize_piper(spec, wav_path, piper_model)
    else:
        generator = _synthesize_espeak(spec, wav_path)

    gender = str(spec["gender"])
    age = str(spec["age_range"])
    role = str(spec["role"])
    metadata = {
        "language": "pt-BR",
        "gender": gender,
        "age_range": age,
        "tags": [gender, age, role],
        "role": role,
        "license": (
            "Generated offline for audiobook-ai MVP seed via "
            f"{generator}; prefer Piper pt_BR / Kokoro BR for production refs."
        ),
        "provenance": {
            "generator": generator,
            "script": "scripts/seed_pt_br_voices.py",
            "espeak_voice": spec.get("espeak_voice"),
            "pitch": spec.get("pitch"),
            "speed": spec.get("speed"),
            "piper_model_hint": spec.get("piper_model_hint"),
        },
    }
    (directory / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"seeded {voice_id} via {generator}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--engine",
        choices=("espeak", "piper"),
        default="espeak",
        help="Offline synthesizer (default: espeak)",
    )
    parser.add_argument(
        "--piper-model",
        type=Path,
        default=None,
        help="Path to a Piper pt_BR onnx model (required for --engine piper)",
    )
    parser.add_argument(
        "--voices-root",
        type=Path,
        default=None,
        help="Override assets/voices destination",
    )
    args = parser.parse_args(argv)

    voices_root = args.voices_root or (repo_root() / "assets" / "voices")
    voices_root.mkdir(parents=True, exist_ok=True)

    for spec in VOICE_SPECS:
        seed_one(
            spec,
            voices_root=voices_root,
            engine=args.engine,
            piper_model=args.piper_model,
        )
    print(f"done: {len(VOICE_SPECS)} voices under {voices_root}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
