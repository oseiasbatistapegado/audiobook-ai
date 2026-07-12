# Smoke test manual (MVP + GPU-safe chunked pipeline)

Pré-requisitos no PATH: `ffmpeg` (via `direnv allow` / `direnv reload` na raiz), Ollama com o modelo escolhido, extra `tts-fish` + fish-speech instalados, GPU usável (alvo: **AMD RX 7900 XTX 24 GB / ROCm / Hyprland**). **Não** é necessário subir `api_server` nem Docker compose do Fish Speech.

## Arquitetura relevante

- O processo da CLI **não** carrega Parler nem Fish na GPU.
- **Voice Design** e **Fish Speech** rodam em workers isolados; exit do worker = hard reclaim.
- Síntese é por `SpeechChunk` com manifest em `out/<book_id>/manifest.json` (resume).
- Thresholds de VRAM (defaults em `config.py`; override via CLI/env):
  - `--hard-floor-mib` / `AUDIOBOOK_AI_HARD_FLOOR_MIB` (default 300)
  - `--before-chunk-target-mib` / `AUDIOBOOK_AI_BEFORE_CHUNK_TARGET_MIB` (default 768)
  - `--fish-before-load-target-mib` / `AUDIOBOOK_AI_FISH_BEFORE_LOAD_TARGET_MIB` (default produto **8192** para `s1-mini`; preset **22528** com `--fish-model s2-pro` sem override)
  - `--parler-before-load-target-mib` / `AUDIOBOOK_AI_PARLER_BEFORE_LOAD_TARGET_MIB` (placeholder calibrável)
  - `--tts-max-chunk-chars` / `AUDIOBOOK_AI_TTS_MAX_CHUNK_CHARS` (default produto **200** para `s1-mini`; preset **80** com `s2-pro` sem override)
  - `--fish-model` / `AUDIOBOOK_AI_FISH_MODEL` (`s1-mini` | `s2-pro`, default `s1-mini`)
  - Process allocator reserve: `GPU_PROCESS_RESERVE_MIB=1536` (Fish/Parler workers) so synth peaks OOM the worker instead of the compositor
  - Fish residency: **guardian-driven** by default (`FISH_CHUNKS_PER_WORKER=0`). Hard reclaim mid-fase só sob progressive growth / headroom. Escape hatch: `--fish-chunks-per-worker N` / `AUDIOBOOK_AI_FISH_CHUNKS_PER_WORKER` (N>0)

**Critério de estabilidade do compositor:** durante o smoke multi-chunk o Hyprland/Wayland deve permanecer estável (sem freeze/crash por pressão de VRAM). OOM **não** é controle normal. Em RX 7900 XTX, dips transitórios de free VRAM abaixo de 300 MiB ainda podem aparecer no meio da síntese sob `GPU_PROCESS_RESERVE_MIB=1536`; o reserve do allocator é a mitigação (worker OOM antes de matar o desktop). Evidência: `out/smoke_gpu_v3/smoke_report.json`.

## 1. Ambiente e install TTS

```bash
cd /path/to/narrative_compiler_py
direnv allow && direnv reload   # se necessário — traz ffmpeg via flake.nix
which ffmpeg
uv sync --group dev --extra tts-fish --extra voice-parler
uv pip install --no-deps "fish-speech @ git+https://github.com/fishaudio/fish-speech@v2.0.0-beta"
uv pip install --no-deps "parler-tts @ git+https://github.com/huggingface/parler-tts.git"
```

Critério de bootstrap:

```bash
uv run python -c "import torch; import fish_speech"
# Voice Design:
uv run python -c "from parler_tts import ParlerTTSForConditionalGeneration"
```

## 2. Ollama (LLM)

```bash
curl -s http://localhost:11434/api/tags | head
ollama pull qwen3:8b
# opcional qualidade: ollama pull qwen3.6:27b
```

S1-mini (default Fish) é **gated** no Hugging Face:

```bash
hf auth login
# aceite os termos em https://huggingface.co/fishaudio/openaudio-s1-mini
```

## 3. Primeira execução (download de pesos + workers)

```bash
uv run audiobook-ai generate samples/sample.pdf --output out/sample.m4b
# qualidade máxima Fish (mais lento): --fish-model s2-pro
```

Espere etapas Rich: `preflight` → `interpret` → `voice-design` / `gpu-worker` → `vram-handoff` (release-verified) → `tts` / chunks → `merge`.

Artefatos resumíveis:

- `out/<book_id>/story.json`
- `out/<book_id>/manifest.json`
- `out/<book_id>/audio/chunk-XXXXXX.wav`
- `out/<book_id>/jobs/` (IPC dos workers)
- `out/<book_id>/logs/`

Pesos Fish: `~/.cache/audiobook-ai/fish-s1-mini/` (ou `fish-s2-pro/`). Vozes: `~/.cache/audiobook-ai/voices/<book_id>/`.

## 4. Resume / segunda execução

```bash
uv run audiobook-ai generate samples/sample.pdf --output out/sample.m4b
```

- Cache de pesos: `model-ensure: cache hit` (sem re-download completo).
- Chunks `completed` no manifest: CLI indica `tts-resume` / skip — **não** regenera tudo.

### Resume no meio (manual)

1. Interrompa (Ctrl+C) durante a fase Fish após ≥1 chunk persistido.
2. Rode de novo o mesmo comando.
3. Confirme que chunks completed não são regenerados; só pendentes seguem.

## 5. Smoke multi-chunk (≥5 SpeechChunks) — RX 7900 XTX

Com texto longo o bastante (ou `--tts-max-chunk-chars` baixo) para produzir ≥5 chunks:

1. Voice Design worker → verify release → Fish worker.
2. Fish permanece residente enquanto o guardian considerar headroom seguro; cold start só sob `restart_reason=progressive` / `headroom` (ou teto opcional) / fim de fase.
3. Sem crescimento progressivo unbounded; hard floor não violado deliberadamente.
4. Merge ordenado pelo manifest.
5. Hyprland estável.

Para smoke de residency guardian-driven, preferir **≥20 SpeechChunks** e confirmar nos logs que NÃO há `restart_reason=residency` com default (teto 0).

### Política de OOM / stall (Fish)

- Restarts por `unexpected_oom` continuam enquanto houver progresso (novos chunks `completed`).
- Abort por **stall**: `FISH_OOM_NO_PROGRESS_LIMIT` (default 3) restarts cobrados consecutivos sem chunk novo completed.
- Abort por **mesmo chunk**: `FISH_CHUNK_MAX_OOM_ATTEMPTS` (default 3) OOMs no mesmo `oom_chunk_id`.
- `FISH_WORKER_RESTART_BUDGET` default **0** (desabilitado); só ative se quiser um teto global absoluto.
- Planned reclaim (`progressive` / `headroom` / `residency`) não cobra stall/OOM.
- No spawn do Fish, o orquestrador injeta `expandable_segments:True` em `PYTORCH_HIP_ALLOC_CONF` e `PYTORCH_CUDA_ALLOC_CONF` se o usuário não as tiver definido (mitiga fragmentação HIP).

Calibração pós-smoke (registrar em `design.md` da change): `tts_max_chunk_chars`, Parler `before_load_target_mib`, ajustes finos de K/N se necessário. Defaults produto: S1-mini load **8192** / chunk **200**; preset s2-pro **22528** / **80**.

## 6. Sucesso esperado

- exit code `0`
- arquivo de saída (ex. `out/sample.m4b`)
- manifest com chunks completed e WAVs sob `out/<book_id>/audio/`
- pesos no cache de modelos (não em `out/`)
- falhas de VRAM classificadas (load / headroom / release / progressive growth) — **não** OOM como controle

Se o preflight falhar cedo (ffmpeg, Ollama, modelo, ou imports TTS), a mensagem cita a correção e **não** inicia download de pesos.
