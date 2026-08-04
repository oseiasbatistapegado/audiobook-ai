## 1. Lower Parler VRAM threshold

- [x] 1.1 Change `PARLER_BEFORE_LOAD_TARGET_MIB` from 8192 to 4096 in `src/audiobook_ai/config.py`

## 2. Load Parler model in FP16

- [x] 2.1 Update `ParlerVoiceGenerator._ensure_model()` to load with `torch_dtype=torch.float16`
- [x] 2.2 Add a log line reporting dtype and expected weight size at load time

## 3. Batch voice-design post-interpretation

- [x] 3.1 In `pipeline.py`, collect all new character IDs across chapters (no per-chapter `run_voice_design_phase` call)
- [x] 3.2 After the `for chapter in book.chapters` loop, spawn a single `run_voice_design_phase` with all accumulated `missing_character_ids`
- [x] 3.3 Handle the resume case: when resuming from `interpret_progress.json`, only batch characters new to the remaining chapters
- [x] 3.4 Verify `dialogues_to_chunks` and `enrich_chunk_voices` still work correctly when `story.voice_map` is empty during interpretation (they default to narrator)

## 4. Update tests

- [x] 4.1 Add or update test verifying `PARLER_BEFORE_LOAD_TARGET_MIB = 4096`
- [x] 4.2 Add or update test verifying Parler model loads with `torch.float16`
- [x] 4.3 Add test for the batched voice-design flow (one spawn for all characters)
- [x] 4.4 Verify existing VRAM guardian tests still pass with the new threshold

## 5. Verification

- [x] 5.1 Run `uv run pytest` to confirm all tests pass
- [x] 5.2 Run a full pipeline with a multi-chapter book (or the same book) to confirm no voice-design failures
