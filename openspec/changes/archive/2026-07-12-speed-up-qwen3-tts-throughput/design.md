## Context

Qwen3-TTS 0.6B peaks near ~3 GB on RX 7900 XTX (24 GB). The Fish-era pipeline still: (1) restarts on absolute free-drop (`progressive_growth` at 256 MiB / K=3) while ~20 GB free and allocated stable; (2) unload/reload TTS per chapter; (3) uses 500-char chunks with high per-chunk overhead. Observed wall-clock is dominated by TTS RTF plus false restarts.

## Goals / Non-Goals

**Goals:**

- Cut end-to-end PDF→M4B wall-clock by ≥50% vs pre-change baseline on the same hardware/book.
- `TTS_MAX_CHUNK_CHARS=5000` as product default (no calibration ladder).
- Guardian progressive restarts only under real memory pressure.
- Continuous TTS phase with resident worker across chapters when safe.
- VoiceClonePrompt cache per `voice_id` for worker lifetime.
- Official batching / CPU–GPU overlap when available without breaking resume/order.

**Non-Goals:**

- Restoring Fish / dual-backend / model swap.
- Calibration series `500→1000→2000→4000`.
- Multiple default model instances.
- Sacrificing voice identity, resume, persist-before-reclaim, or deterministic chunk order.

## Decisions

### D1 — Chunk size 5000

Set `TTS_MAX_CHUNK_CHARS=5000`. Chunker still one dialogue turn per preferred unit; only splits a single turn when it exceeds 5000. Does not concatenate independent dialogues/speakers.

### D2 — Progressive growth = real pressure

Restart for progressive growth only when:

- `allocated_mib` and/or `reserved_mib` show persistent growth over the window **AND/OR**
- `free_mib` approaches `hard_floor_mib` (configurable margin),

not merely when free drops by an absolute N MiB while allocated/reserved are stable and free remains far above the floor. Keep hard floor, chunk headroom gate, real OOM, stall, and no-progress protections.

### D3 / D4 — Continuous TTS residency

Restructure generate flow toward:

1. Interpret (+ voice design as needed) for chapters, then **one** continuous TTS phase over pending SpeechChunks; **or** keep chapter interpret loop but **do not** release/reload TTS between chapters when the next work is more TTS and LLM is already unloaded.

Preferred: after all interpretation (and voice design) for the run’s pending chapters, spawn TTS once and drain the full pending manifest. Preserve controlled restart + resume.

Minimal viable path if full two-pass is too large: keep chapter loop for LLM, but hold TTS lease across consecutive TTS-only chapters without LLM in between — still wrong for current per-chapter interpret. **Target architecture:** two-pass — interpret all chapters (LLM unload between each if needed for VRAM, or once at end), voice-design batch once, then single TTS residency for all pending chunks.

Practical implementation for this change:

- Pass A: for each chapter → interpret → apply story → collect dialogues into manifest chunks; voice-design as characters appear (Parler worker, release verified).
- Pass B: single `run_tts_phase` over all pending chunks with one worker residency (restarts only for real reclaim).
- Pass C: merge.

### D5 — VoiceClonePrompt cache

Already partially present in `Qwen3TTSBackend._voice_prompts`. Ensure `create_voice_clone_prompt` path is always used when available; cache survives for worker process lifetime; cleared on `release()` / process exit. Verify no per-chunk re-encode of refs.

### D6 — Batching / concurrency

Probe `generate_voice_clone` for multi-text / batch API. If supported with same prompt, batch consecutive pending chunks that share `voice_id` (and compatible metadata) up to a small batch size, still persist each SpeechChunk id in order. If not supported, document and skip multi-instance.

### D7 — CPU/GPU overlap

Within worker: prepare next request (paths, TTSRequest, prompt cache hit) while GPU runs current synth when the API is sync-only via a simple prep queue / double-buffer. Persist remains after each successful synth before reclaim. Do not mark completed until bytes are on disk.

## Risks / Trade-offs

- [Longer chunks hurt prosódia] → Accept product decision; quality regressions tracked as follow-up, not calibration gate in this change.
- [Two-pass delays first audio] → Acceptable for throughput goal.
- [Relaxed progressive misses a real slow leak] → Mitigate with allocated/reserved trend + hard floor approach; OOM path unchanged.
- [Fingerprint invalidates mid-run resumes] → Document; regenerate TTS phase.
- [Batching reorders or merges speakers] → Batch only same voice_id consecutive chunks; never merge texts across speakers into one SpeechChunk id.

## Migration Plan

1. Ship defaults + guardian + residency + cache.
2. Existing runs with old fingerprint regenerate TTS.
3. Rollback: revert commit / restore prior config defaults.

## Open Questions

None blocking — product decisions D1–D7 are fixed by the implementation directive.
