# Fix Parler VRAM threshold to fit 24 GB GPUs

## Why

Voice Design phase fails on 24 GB GPUs (RX 7900 XTX) with the error
`unsafe to load backend=parler: free_mib=7012.1 below before_load_target_mib=8192`.
The `PARLER_BEFORE_LOAD_TARGET_MIB` constant (8192 MiB) is an uncalibrated placeholder.
The Parler-TTS-mini model is only ~0.6B parameters (~2.4 GB FP32, ~1.2 GB FP16),
and the actual system VRAM available after Ollama unload is ~7 GB on a 24 GB card.

## What Changes

- **Reduce `PARLER_BEFORE_LOAD_TARGET_MIB`** from 8192 to 4096 MiB (4 GB),
  sufficient for a 2.4 GB model + tokenizers + margin on a 24 GB card
  (with ~7 GB free post-Ollama-unload).
- **Load Parler model in FP16** via `.half()`, cutting peak VRAM usage
  from ~2.4 GB to ~1.2 GB for weights.
- **Batch voice-design** into a single post-interpretation pass instead of
  per-chapter spawns. All new characters discovered during interpretation
  are processed after the last chapter, eliminating N-1 redundant worker
  spawns and VRAM gate checks.

## Capabilities

### Modified Capabilities
- `generative-voice-design`: VRAM loading threshold and batch processing

## Impact

| Area | Files | Impact |
|------|-------|--------|
| Config | `src/audiobook_ai/config.py` | `PARLER_BEFORE_LOAD_TARGET_MIB` lowered |
| Voice Generator | `src/audiobook_ai/voice/generator.py` | FP16 loading for Parler model |
| Pipeline | `src/audiobook_ai/pipeline.py` | Move voice-design to post-interpretation batch |
| Orchestrate | `src/audiobook_ai/gpu/orchestrate.py` | Adjust batch job parameters |
| Lifecycle | `src/audiobook_ai/gpu/lifecycle.py` | Release target logic may simplify |
| Tests | `tests/` | Update VRAM threshold tests |
