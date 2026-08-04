## Why

Parler-TTS voice generation fails with `'DynamicCache' object has no attribute 'key_cache'` when running on GPU (ROCm/CUDA).

**Root cause investigation (2025-07-31):**

The error is **not** caused by installing `parler-tts` from git HEAD — `parler-tts==0.2.3` is already pinned in `scripts/bootstrap_parler_venv.sh` and confirmed installed.

The real issue is a **cache type mismatch** in the Parler-TTS attention layers. The Parler-TTS code at lines 532, 659, 874 of `modeling_parler_tts.py` accesses `past_key_value.key_cache[self.layer_idx]` after unwrapping the `EncoderDecoderCache`:

```python
# Line 520-526 (ParlerTTSAttention.forward)
is_updated = past_key_value.is_updated.get(self.layer_idx)
if is_cross_attention:
    past_key_value = past_key_value.cross_attention_cache
else:
    past_key_value = past_key_value.self_attention_cache  # → DynamicCache

# Line 530-533
if is_cross_attention and past_key_value and is_updated:
    key_states = past_key_value.key_cache[self.layer_idx]  # CRASH
```

On GPU (ROCm), the unwrapped `past_key_value` may be a `Cache` base class instance (from `transformers.cache_utils`) that lacks the `key_cache` and `value_cache` attributes, even though `DynamicCache` defines them in `__init__`. The `EncoderDecoderCache.__init__` stores `self_attention_cache` and `cross_attention_cache` as plain `Cache` references, and the unwrapping discards the `is_updated` dict that lives on the wrapper, not on `DynamicCache` instances.

**Fix:** Add a monkey-patch to `DynamicCache` in `_patch_parler_tts_config()` that provides `key_cache` and `value_cache` as property-style accessors delegating to `layers` (the modern cache API in transformers >= 4.46), making the legacy `key_cache[layer_idx]` access pattern resilient regardless of which `Cache` subclass is unwrapped.

## What Changes

- Add monkey-patch in `_patch_parler_tts_config()` that injects `key_cache`/`value_cache` properties onto `DynamicCache`
- Keep existing `parler-tts==0.2.3` pin in `scripts/bootstrap_parler_venv.sh` (already correct)
- Keep existing `transformers==4.46.1` pin in `scripts/bootstrap_parler_venv.sh` (already correct)
- Keep all existing conditional patches in `_patch_parler_tts_config()` (already correct)

## Capabilities

### Modified Capabilities

- `voice-generation`: Add resilience patch for `DynamicCache.key_cache` to prevent GPU crash in Parler-TTS voice generation

## Impact

- `src/audiobook_ai/voice/generator.py`: Add monkey-patch for `DynamicCache.key_cache`/`value_cache` in `_patch_parler_tts_config()`
- `scripts/bootstrap_parler_venv.sh`: No changes needed (already pins parler-tts==0.2.3)
- `pyproject.toml`: No changes needed (voice-parler extra already has parler-tts comment)
