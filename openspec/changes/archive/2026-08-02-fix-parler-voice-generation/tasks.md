## 1. Implement DynamicCache monkey-patch in `_patch_parler_tts_config()`

- [x] 1.1 Edit `src/audiobook_ai/voice/generator.py` — add monkey-patch for `DynamicCache.key_cache`/`value_cache` properties at end of `_patch_parler_tts_config()`, before `ParlerTTSConfig._patched = True`
- [x] 1.2 The patch must:
  - Import `DynamicCache` from `transformers.cache_utils`
  - Define `@property` methods `_dc_key_cache` and `_dc_value_cache` that delegate to `self.layers` (modern API) or return empty list
  - Assign properties to `DynamicCache.key_cache` and `DynamicCache.value_cache`
  - Guard against double-patch with `if not hasattr(DynamicCache, "key_cache")`
  - Mark patched with `DynamicCache._patched = True`
- [x] 1.3 The patch must be **unconditional** (not inside `_TRANSFORMERS_457` block) because it fixes a bug in transformers 4.46.1 (Parler's target version)
- [x] 1.4 Verify: `_patch_parler_tts_config()` runs without error, and `DynamicCache.key_cache`/`value_cache` properties exist

## 2. Validate voice generation on GPU

- [x] 2.1 Run `uv run audiobook-ai generate <pdf>` with a test book and verify voice generation completes without `DynamicCache.key_cache` error
- [x] 2.2 Run `uv run pytest` to ensure no regressions

## 3. Clean up (optional)

- [x] 3.1 Verify `scripts/bootstrap_parler_venv.sh` already has `parler-tts==0.2.3` pin (line 56) — no change needed
- [x] 3.2 Verify `pyproject.toml` has comment about `parler-tts==0.2.3` (line 36) — no change needed
- [x] 3.3 Update comments in `pyproject.toml` if needed to reflect that the fix is in code (monkey-patch), not just dependency pinning
