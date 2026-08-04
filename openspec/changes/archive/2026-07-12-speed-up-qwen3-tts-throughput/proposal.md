## Why

Qwen3-TTS 0.6B uses ~3 GB VRAM on a 24 GB RX 7900 XTX, but the pipeline still applies Fish-era defensive policies (false `progressive_growth` restarts, per-chapter unload/reload, 500-char chunks). Wall-clock PDF→M4B stays far above what the light actor should allow. We need ≥50% reduction in total generation time without sacrificing voice identity, resume, or real OOM safety.

## What Changes

- Raise `TTS_MAX_CHUNK_CHARS` to **5000** (product decision; no `500→4000` calibration ladder).
- Retarget Guardian `progressive_growth` to real memory pressure (allocated/reserved growth and/or free near hard floor), not absolute free-drop false positives at ~20 GB free.
- Keep Qwen3-TTS resident for continuous TTS work across chapters; unload only when TTS phase ends or real reclaim is required.
- Prefer Interpretation phase → continuous TTS phase → Merge to amortize load/init/caches.
- Cache `VoiceClonePrompt` per `voice_id` inside the TTS worker for the process lifetime.
- Use official Qwen3-TTS batching/concurrency when available; prefer single-instance batching over multiple model copies.
- Overlap safe CPU prep/persist with GPU generation without breaking determinism, resume, or persist-before-reclaim.
- **BREAKING** for in-flight resumes: chunking fingerprint changes with `TTS_MAX_CHUNK_CHARS=5000`, so prior TTS manifests under the old fingerprint regenerate the TTS phase.

## Capabilities

### New Capabilities

- (none)

### Modified Capabilities

- `speech-chunking`: default max chunk size becomes 5000; still no cross-speaker merge.
- `vram-guardian`: progressive growth requires real pressure signals.
- `gpu-lifecycle`: TTS worker residency across continuous TTS work.
- `vram-handoff`: allow continuous TTS phase instead of per-chapter exclusivity when safe.
- `tts-qwen3`: VoiceClonePrompt cache; batching/overlap when API supports it.
- `chunk-resume`: fingerprint invalidation on chunk-size change remains; residency must not break resume.
- `generate-cli`: expose/document any CLI knobs affected by residency/chunk defaults if present.

## Impact

- Config defaults (`TTS_MAX_CHUNK_CHARS`, progressive growth thresholds).
- `gpu/guardian.py`, TTS worker, `pipeline.py` / `gpu/orchestrate.py` phase structure.
- `tts/qwen3_tts.py` prompt cache and optional batching.
- Tests for guardian, chunking, lifecycle, TTS worker, pipeline handoff.
- Docs/SMOKE notes for new defaults and expected speedup measurement.
