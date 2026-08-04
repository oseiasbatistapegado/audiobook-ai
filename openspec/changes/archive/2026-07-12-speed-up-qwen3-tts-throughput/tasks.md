## 1. Chunk size 5000

- [x] 1.1 Set `TTS_MAX_CHUNK_CHARS=5000` in config and update chunking fingerprint consumers/tests/docs/CLI defaults
- [x] 1.2 Confirm dialogue chunker still never merges distinct speakers/turns; only splits oversized single turns

## 2. Guardian progressive growth

- [x] 2.1 Change `ProgressiveGrowthDetector` to require real pressure (allocated/reserved growth and/or free near hard floor)
- [x] 2.2 Update guardian tests for false-positive free-drop vs real growth / near-floor cases
- [x] 2.3 Adjust config knobs/docs for the new progressive policy

## 3. Continuous TTS residency

- [x] 3.1 Restructure pipeline to Interpretation (+ voice design) then continuous TTS phase over pending manifest chunks
- [x] 3.2 Keep Qwen3-TTS worker resident across chapters within the TTS phase; unload only at phase end or real reclaim
- [x] 3.3 Update vram-handoff / lifecycle / pipeline tests for continuous TTS

## 4. VoiceClonePrompt cache + overhead

- [x] 4.1 Ensure VoiceClonePrompt is cached per `voice_id` for worker lifetime; add/adjust unit tests
- [x] 4.2 Probe Qwen3-TTS API for batching; implement same-voice batching if supported, else document skip
- [x] 4.3 Reduce inter-chunk idle (prep next request / overlap CPU while preserving persist-before-reclaim)

## 5. Validation

- [x] 5.1 Run affected unit tests (chunking, guardian, lifecycle, tts, pipeline)
- [x] 5.2 Note expected wall-clock measurement approach for ≥50% goal (SMOKE/docs)
