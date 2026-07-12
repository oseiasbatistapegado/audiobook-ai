"""Central configuration defaults for the audiobook pipeline."""

from __future__ import annotations

from pathlib import Path

from audiobook_ai.models.emotion import Emotion
from audiobook_ai.models.voice import CANONICAL_VOICE_LANGUAGE

DEFAULT_OLLAMA_MODEL: str = "qwen3:8b"
DEFAULT_OLLAMA_HOST: str = "http://localhost:11434"
DEFAULT_WORK_DIR: Path = Path("out")
DEFAULT_OUTPUT_NAME: str = "audiobook.m4b"
DEFAULT_TTS_BACKEND: str = "fish-speech"
# Fish open-weight alias (CLI --fish-model / AUDIOBOOK_AI_FISH_MODEL).
DEFAULT_FISH_MODEL: str = "s1-mini"
DEFAULT_CACHE_DIR: Path | None = None  # resolved by weights.cache.resolve_cache_root

ALLOWED_EMOTIONS: tuple[Emotion, ...] = tuple(Emotion)

# Dedicated narrator voice id (packaged under assets/voices/narrator/).
DEFAULT_VOICE_ID: str = "narrator"
NARRATOR_VOICE_ID: str = DEFAULT_VOICE_ID
# Back-compat alias used by older call sites; only the narrator id is listed.
DEFAULT_VOICE_REFERENCE_IDS: tuple[str, ...] = (NARRATOR_VOICE_ID,)

VOICE_LANGUAGE: str = CANONICAL_VOICE_LANGUAGE
VOICE_BANK_VERSION: str = "v1"  # bank/dev only; not product seed material
VOICE_GENERATOR_DEFAULT: str = "parler"
VOICES_CACHE_SUBDIR: str = "voices"
# Generative Voice Design (Parler-TTS pt-BR).
PARLER_MODEL_ID: str = "freds0/parler-tts-mini-v1.1-ptbr"
PARLER_GENERATOR_VERSION: str = "1"
# Short refs for Fish Speech on 24GB ROCm (packaged bank ~5–7s).
VOICE_REF_MAX_SECONDS: float = 6.0

# --- VRAM guardian thresholds (MiB). Defaults only; CLI/env may override. ---
# Never deliberately start GPU work below this system-reported free VRAM.
HARD_FLOOR_MIB: int = 300
# Back-compat alias for call sites that still use the old name.
MIN_FREE_VRAM_MIB: int = HARD_FLOOR_MIB
# Desired free headroom before the next SpeechChunk with a model resident.
BEFORE_CHUNK_TARGET_MIB: int = 768
# Backend-specific free VRAM required before load/spawn. Unknown backends
# MUST NOT silently inherit the Fish value.
# Product default targets OpenAudio S1-mini; s2-pro uses the preset below
# when --fish-model s2-pro is selected without an explicit load override.
FISH_BEFORE_LOAD_TARGET_MIB: int = 8192
FISH_S2_PRO_BEFORE_LOAD_TARGET_MIB: int = 22528
# Placeholder until RX 7900 XTX smoke calibrates Parler (MUST stay separate).
PARLER_BEFORE_LOAD_TARGET_MIB: int = 8192
BACKEND_LOAD_TARGET_MIB: dict[str, int] = {
    "fish-speech": FISH_BEFORE_LOAD_TARGET_MIB,
    "parler": PARLER_BEFORE_LOAD_TARGET_MIB,
}

# SpeechChunk sizing (chars). Product default for S1-mini; s2-pro preset is 80.
TTS_MAX_CHUNK_CHARS: int = 200
FISH_S2_PRO_TTS_MAX_CHUNK_CHARS: int = 80

# Progressive VRAM growth detection (sliding window after reclaim).
PROGRESSIVE_GROWTH_WINDOW_K: int = 3
PROGRESSIVE_GROWTH_DROP_MIB: int = 256

# Fish worker OOM / restart policy (controlled restarts; excludes the initial worker).
# Primary gates: stall (no new completed chunks) and per-chunk OOM attempts.
# Unexpected OOM / non-planned reasons charge these; planned reclaim does not.
FISH_OOM_NO_PROGRESS_LIMIT: int = 3
FISH_CHUNK_MAX_OOM_ATTEMPTS: int = 3
# Optional absolute ceiling on charged restarts. 0 = disabled (default).
# Prefer stall / per-chunk gates; enable only when a hard global cap is desired.
FISH_WORKER_RESTART_BUDGET: int = 0
# Total attempts per SpeechChunk id (first try + one retry) for hard failures.
# Unexpected OOM / controlled restart MUST NOT burn these (OOM uses gates above).
SPEECH_CHUNK_MAX_ATTEMPTS: int = 2
# Optional residency ceiling (escape hatch). Primary reclaim is guardian-driven
# (progressive growth / before_chunk headroom). 0 = disabled (default).
# Value >0 forces EXIT after N successful chunks with restart_reason=residency.
FISH_CHUNKS_PER_WORKER: int = 0

# ROCm free VRAM can lag process exit / Ollama keep_alive=0; poll before gating.
VRAM_RELEASE_POLL_S: float = 0.5
VRAM_RELEASE_WAIT_TIMEOUT_S: float = 120.0

# MiB reserved from this process's CUDA/HIP allocator for compositor / desktop.
# Empirical RX 7900 XTX (2026-07-12):
# - 1536: Fish can synth (peak calib 120 chars min free ≈301.5; multi-chunk
#   dips possible — mitigate with smaller chunks + guardian-driven reclaim).
# - 1792/2560: too tight — Fish OOMs on ≤80-char chunks while system free ≫300.
GPU_PROCESS_RESERVE_MIB: int = 1536

STORY_FILENAME: str = "story.json"
MANIFEST_FILENAME: str = "manifest.json"
CHAPTERS_SUBDIR: str = "chapters"
AUDIO_SUBDIR: str = "audio"
JOBS_SUBDIR: str = "jobs"
CACHE_SUBDIR: str = "cache"
LOGS_SUBDIR: str = "logs"

LLM_PROMPT_FILE: str = "interpret_chapter.md"
LLM_CACHE_ENABLED: bool = True
# Stable cache-key fragment for dialogue output locale + adaptation policy.
# Bump LLM_ADAPTATION_POLICY_VERSION when the adaptation rules change.
LLM_OUTPUT_LOCALE: str = "pt-BR"
LLM_ADAPTATION_POLICY_VERSION: str = "v1"
