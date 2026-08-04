"""Central configuration defaults for the audiobook pipeline."""

from __future__ import annotations

from pathlib import Path

from audiobook_ai.models.emotion import Emotion
from audiobook_ai.models.voice import CANONICAL_VOICE_LANGUAGE

DEFAULT_LLAMA_MODEL: str = "localweights/Qwen3.6-35B-A3B-MTP-IQ4_XS-GGUF"
DEFAULT_LLAMA_HOST: str = "http://127.0.0.1:8080"
DEFAULT_TEMPERATURE: float = 0.7
DEFAULT_WORK_DIR: Path = Path("out")
DEFAULT_OUTPUT_NAME: str = "audiobook.m4b"
DEFAULT_TTS_BACKEND: str = "qwen3-tts"
DEFAULT_CACHE_DIR: Path | None = None  # resolved by weights.cache.resolve_cache_root
# Parler decode dependency (pinned; discovered without fish-speech).
DAC_PACKAGE: str = "descript-audio-codec"
DAC_VERSION: str = "1.0.0"

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
BEFORE_CHUNK_TARGET_MIB: int = 512
# Backend-specific free VRAM required before load/spawn. Unknown backends
# MUST NOT silently inherit another backend's value.
# Qwen3-TTS Base (~2.8 GB real usage). 3072 MiB = peak + minimal operational margin.
TTS_BEFORE_LOAD_TARGET_MIB: int = 3072
# Calibrated for RX 7900 XTX (24 GB): Ollama leaves ~7 GB; Parler + tokenizers peak ~3 GB FP32 / ~1.5 GB FP16.
PARLER_BEFORE_LOAD_TARGET_MIB: int = 4096
BACKEND_LOAD_TARGET_MIB: dict[str, int] = {
    "tts": TTS_BEFORE_LOAD_TARGET_MIB,
    "qwen3-tts": TTS_BEFORE_LOAD_TARGET_MIB,
    "parler": PARLER_BEFORE_LOAD_TARGET_MIB,
}

# SpeechChunk sizing (chars). Product default for Qwen3-TTS Base (light VRAM).
TTS_MAX_CHUNK_CHARS: int = 5000

# Progressive VRAM growth detection (real pressure, not free-drop noise).
PROGRESSIVE_GROWTH_WINDOW_K: int = 3
# Legacy free-drop threshold (kept for JobConfig compat; no longer primary trigger).
PROGRESSIVE_GROWTH_DROP_MIB: int = 256
# Persistent growth in allocated OR reserved over the window → real pressure.
PROGRESSIVE_ALLOCATED_GROWTH_MIB: int = 256
# Restart when free_mib <= hard_floor_mib + this margin.
PROGRESSIVE_FLOOR_MARGIN_MIB: int = 512

# TTS worker OOM / restart policy (controlled restarts; excludes the initial worker).
TTS_OOM_NO_PROGRESS_LIMIT: int = 3
TTS_CHUNK_MAX_OOM_ATTEMPTS: int = 3
# Optional absolute ceiling on charged restarts. 0 = disabled (default).
TTS_WORKER_RESTART_BUDGET: int = 0
# Total attempts per SpeechChunk id (first try + one retry) for hard failures.
SPEECH_CHUNK_MAX_ATTEMPTS: int = 2
# Optional residency ceiling (escape hatch). 0 = disabled (default).
TTS_CHUNKS_PER_WORKER: int = 0
# Max SpeechChunks sharing a voice_id to submit in one generate_voice_clone call.
TTS_SAME_VOICE_BATCH_SIZE: int = 8

# Multi-worker TTS: number of parallel TTS worker processes (max 4).
# 1 = single-worker (original behaviour); 2 = default for 24 GB GPU.
TTS_MULTI_WORKER_COUNT: int = 2
TTS_MULTI_WORKER_MAX: int = 4

# Async pipeline overlap: chapters of LLM ahead of TTS.
# 0 = linear pipeline; 1 = default (LLM cap N+1 while TTS cap N).
TTS_ASYNC_OVERLAP: int = 1
TTS_ASYNC_OVERLAP_MAX: int = 3

# VRAM headroom per worker (model + overhead). Used to calculate
# before_multi_worker_load_mib = worker_count * per_worker_mib.
TTS_PER_WORKER_VRAM_MIB: int = 2800
TTS_PER_WORKER_OVERHEAD_MIB: int = 200

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
INTERPRET_PROGRESS_FILENAME: str = "interpret_progress.json"
CHAPTERS_SUBDIR: str = "chapters"
AUDIO_SUBDIR: str = "audio"
JOBS_SUBDIR: str = "jobs"
CACHE_SUBDIR: str = "cache"
LOGS_SUBDIR: str = "logs"

LLM_PROMPT_FILE: str = "interpret_chapter.md"
LLM_CAST_DISCOVERY_PROMPT_FILE: str = "discover_cast.md"
LLM_CACHE_ENABLED: bool = True
# Stable cache-key fragment for dialogue output locale + adaptation policy.
# Bump LLM_ADAPTATION_POLICY_VERSION when the adaptation rules change.
LLM_OUTPUT_LOCALE: str = "pt-BR"
LLM_ADAPTATION_POLICY_VERSION: str = "v5"
# Bump when diarization / speaker-QA / interpret-unit rules change (cache key).
# v5: cache key uses cast fingerprint instead of full story_state dump.
# v6: strip speech-attribution tags from character dialogue text.
# v7: two-pass cast discovery then diarization; narrator-collapse QA.
LLM_DIARIZATION_POLICY_VERSION: str = "v7"
# Max chapter-text characters per Ollama interpretation unit (split above this).
LLM_INTERPRET_MAX_CHARS: int = 6000
# Max source characters per Pass-1 cast-discovery call (full chapter preferred;
# deterministic complete-coverage chunking above this — never head+tail).
LLM_CAST_DISCOVERY_MAX_CHARS: int = 24000
# HTTP request timeout for llama-server calls (None = no timeout).
# Slow models can take >5 min per chapter; disable timeout to prevent spurious failures.
LLM_HTTP_TIMEOUT: float | None = None
LLM_HTTP_CONNECT_TIMEOUT: float = 30.0
# Total attempts per interpretation unit (JSON / schema / speaker QA).
LLM_INTERPRET_MAX_ATTEMPTS: int = 3
# Total attempts per cast-discovery call (JSON / schema).
LLM_CAST_DISCOVERY_MAX_ATTEMPTS: int = 3
# Speaker-QA gate: fail only when all three conditions hold.
LLM_SPEAKER_QA_MIN_QUOTED_TURNS: int = 6
LLM_SPEAKER_QA_DOMINANCE_THRESHOLD: float = 0.85
# Narrator-collapse: speech-like turns mostly assigned to narrator despite
# multiple chapter speakers / evidence.
LLM_SPEAKER_QA_NARRATOR_COLLAPSE_MIN_SPEECH_TURNS: int = 6
LLM_SPEAKER_QA_NARRATOR_COLLAPSE_THRESHOLD: float = 0.85
# Attribution prompt file name.
LLM_ATTRIBUTION_PROMPT_FILE: str = "attribution.md"
# Max correction attempts per unit when QA fails (separate from LLM_INTERPRET_MAX_ATTEMPTS).
QA_CORRECTION_MAX_ATTEMPTS: int = 3
# Top-k candidates returned by the embedding resolver.
SPEAKER_RESOLUTION_TOP_K: int = 3
# Cosine-similarity threshold for attribution embedding gap (secondary evidence).
ATTRIBUTION_EMBEDDING_GAP_THRESHOLD: float = 0.20
# Speaker resolution v2 feature flag (default True).
SPEAKER_RESOLUTION_V2_ENABLED: bool = False
# Debug state serialization dump (default False in production).
DEBUG_STATE_DUMP: bool = False
# Policy version constants — bump to invalidate specific caches.
ATTRIBUTION_POLICY_VERSION: str = "v2"
INTERPRETATION_POLICY_VERSION: str = "v1"
CAST_POLICY_VERSION: str = "v1"
UNIT_CLASSIFIER_VERSION: str = "v1"
TURN_TRACKER_VERSION: str = "v1"
# Candidate generator version (bump to invalidate caches when new steps are added).
CANDIDATE_GENERATOR_VERSION: str = "v1-fp"
# Feature flags for hybrid attribution pipeline.
HYBRID_ATTRIBUTION_ENABLED: bool = True
# Embedding model used by the SpeakerEmbeddingService (fallback step in candidate generation).
EMBEDDING_MODEL: str = "paraphrase-multilingual-MiniLM-L12-v2"
