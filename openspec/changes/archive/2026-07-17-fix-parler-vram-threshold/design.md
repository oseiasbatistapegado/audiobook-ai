## Context

The audiobook pipeline's VRAM guardian gate blocks the Parler voice-design worker
on 24 GB GPUs after Ollama unload. The guardian checks `can_load_backend("parler")`
against `PARLER_BEFORE_LOAD_TARGET_MIB = 8192`, but system-free VRAM is only ~7012 MiB.
The Parler-TTS-mini model is only 0.6B parameters (~2.4 GB FP32), and the threshold
was a placeholder never calibrated for the RX 7900 XTX hardware.

Current flow (per-chapter voice-design):
```
Chapter N: interpret → discover characters → unload Ollama → voice-design → reload Ollama
Chapter N+1: interpret → discover new chars → unload Ollama → voice-design → reload Ollama
```
Each cycle wastes ~130 seconds and fires N-1 redundant VRAM gate checks.

## Goals / Non-Goals

**Goals:**
- Fix the `unsafe to load backend=parler` failure on 24 GB GPUs
- Reduce Parler VRAM peak usage via FP16 loading
- Eliminate per-chapter voice-design overhead; batch into single pass

**Non-Goals:**
- Change the voice-design algorithm (Parler model loading, generation logic)
- Modify the TTS worker GPU management
- Support per-character voice design with different models
- Add FP8 or INT4 quantization (future optimization)

## Decisions

### 1. Lower `PARLER_BEFORE_LOAD_TARGET_MIB` to 4096 MiB

**Rationale:** On a 24 GB card, Ollama occupies ~17.5 GB, leaving ~7 GB.
Parler model + tokenizers peak at ~3.0 GB (FP32) or ~1.5 GB (FP16).
4096 MiB provides a 1 GB safety margin above FP32 peak — sufficient for
safety while fitting the constrained VRAM budget.

**Why not lower to 3072?** On systems where Ollama uses slightly more
(e.g., with KV cache), free VRAM could dip below 6 GB. 3072 would
still work but with less headroom. 4096 is the safer calibrated value.

### 2. Load Parler in FP16 via `.half()`

```python
# Before
self._model = ParlerTTSForConditionalGeneration.from_pretrained(self.model_id).to(device)

# After
self._model = ParlerTTSForConditionalGeneration.from_pretrained(
    self.model_id,
    torch_dtype=torch.float16,
).to(device)
```

**Rationale:** Cuts weight memory from 2.4 GB to 1.2 GB. The model generates
reference audio in FP16 without quality loss (Parler-TTS is known to work
fine in FP16). FP16 is the standard for diffusion-based generative models.

**Alternatives considered:**
- `torch_dtype=torch.bfloat16` — requires ROCm BF16 support verification
- `.half()` post-load — equivalent, but `torch_dtype=` during `from_pretrained`
  is cleaner and avoids a second pass

### 3. Batch voice-design into a single post-interpretation pass

**Current flow:**
```python
for chapter in book.chapters:
    interpret(chapter, story)
    apply_story_updates(story, response)
    missing_voices = [cid for cid in chars if cid not in story.voice_map]
    if missing_voices:
        run_voice_design_phase(story, missing_voices)  # N spawns
```

**New flow:**
```python
for chapter in book.chapters:
    interpret(chapter, story)
    apply_story_updates(story, response)
    # Collect all new characters; defer voice design

# After all chapters — one batched voice-design
all_missing = [cid for cid in all_chars if cid not in story.voice_map]
if all_missing:
    run_voice_design_phase(story, all_missing)  # 1 spawn
```

**Rationale:**
- Reduces worker spawns from N to 1 (130s × (N-1) savings)
- Single VRAM gate check instead of N
- No Ollama unload/reload cycle between chapters
- Simpler lifecycle state (LLM stays resident until TTS phase)

**Trade-offs:**
- Story state and voice_map aren't enriched for chunks until after all
  interpretation completes. This is acceptable — `enrich_chunk_voices`
  handles the case where `voice_map` is empty (assigns narrator by default)
  and enriches after voice-design.

## Risks / Trade-offs

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| FP16 generation quality loss on some hardware | Low | Parler-TTS-mini pt-BR checkpoint is known to work in FP16; existing tests cover generation |
| 4096 MiB insufficient on systems with heavier GPU usage (e.g., compositor, multiple monitors) | Low-Medium | VRAM guardian still provides hard floor (300 MiB); user can override via CLI env var `--parler-load-target-mib` |
| Batched voice-design delays first enriched chunk until all chapters interpreted | Low — acceptable | Only matters for books with 1-2 chapters (edge case); TTS resume still works |
| Per-chapter voice-design was useful for resume on crash mid-book | Medium | Resume works at the interpret-progress level; voice-design batch is re-run on fresh run. For resume from a checkpoint mid-book, the batched design only needs to process newly-discovered characters from remaining chapters. |

## Migration Plan

No migration needed. This is a threshold/config adjustment plus a pipeline
reordering. Existing `story.json`, `manifest.json`, and cache files are
unaffected.

**Deployment:**
1. Land the config + code changes
2. Re-run any books that previously failed at voice-design

**Rollback:**
Revert the `PARLER_BEFORE_LOAD_TARGET_MIB` value to 8192 and revert the
pipeline reordering. No data migration.

## Open Questions

1. **Should we add a CLI flag `--parler-load-target-mib`?** Currently the guardian
   config accepts `parler_load_target_mib` in `run_generate()` and `build_guardian()`,
   and the CLI already exposes it as a Typer option. No additional CLI work needed.
