# Spike Parler-TTS pt-BR — notas

Data: 2026-07-11. Hardware: AMD RX 7900 XTX 24 GB / ROCm 6.4 / torch 2.9.1+rocm6.4.

## Como reproduzir

```bash
uv sync --extra voice-parler --extra tts-fish
uv pip install --no-deps "parler-tts @ git+https://github.com/huggingface/parler-tts.git"
# transformers==4.46.1 required by parler (fish also works on this pin in spike)
python scripts/spike_parler_voice_design.py
python scripts/spike_parler_voice_design.py --skip-generate --with-fish-speech
```

## Outputs

- `out/spikes/parler-voice-design/refs/{carlos,joao}/` — referência completa (~9 s)
- `out/spikes/parler-voice-design/clone_refs/` — truncado a 6 s para Fish
- `out/spikes/parler-voice-design/fish_clones/{carlos,joao}_clone.wav`
- `out/spikes/parler-voice-design/report.json`

## VRAM

Ver tabela em `design.md` (Spike results). Regra do spike: abortar se free &lt; 300 MiB; Fish só carrega com ≥22 GiB free; preferir processo separado para reclaim após Fish.

## Checklist auditivo (humano)

Ouvir nesta ordem:

1. `refs/carlos/reference.wav` vs `refs/joao/reference.wav` — pt-BR? speakers distintos?
2. `fish_clones/carlos_clone.wav` vs `fish_clones/joao_clone.wav` — distinção preservada?

Borderline pt-BR = FAIL.
