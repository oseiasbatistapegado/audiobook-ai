## Why

O soft-cap fixo `FISH_CHUNKS_PER_WORKER=2` força EXIT + cold load (~70 s) a cada dois SpeechChunks mesmo com headroom seguro, dominando o wall-time do TTS em livros longos. O `VRAMGuardian` já detecta queda de free (progressive growth + gate `before_chunk`); a política de residency deve seguir o guardian, não um calendário arbitrário — sem relaxar a regra de no máximo um modelo GPU por vez.

## What Changes

- Remover o EXIT por calendário de residency como política padrão do worker Fish Speech.
- Manter o Fish carregado na mesma invocação do worker enquanto o guardian considerar o headroom seguro; fazer hard reclaim (EXIT do processo) só quando o guardian sinalizar degradação de free VRAM (progressive growth e/ou falha do gate `before_chunk` após reclaim) ou quando não houver mais chunks pendentes na fase.
- Tratar restarts controlados disparados pelo guardian (progressive / headroom) como reclaim planejado: NÃO consumir `FISH_WORKER_RESTART_BUDGET` (mesmo tratamento que o antigo `residency`), para livros longos não abortarem por budget.
- Manter OOM / falhas inesperadas consumindo budget; manter lease exclusivo (Parler XOR Fish XOR overlap com Ollama GPU intencional).
- Opcional: teto de segurança configurável (`FISH_CHUNKS_PER_WORKER`, default desligado/`0`) só como escape hatch — NÃO é a política primária.
- Atualizar docs/SMOKE e testes unitários que assumem restart a cada 2 chunks.

## Capabilities

### New Capabilities

- (nenhuma)

### Modified Capabilities

- `gpu-lifecycle`: política de residency do Fish worker passa a ser guardian-driven; restarts de reclaim saudável não queimam budget; reforçar um modelo GPU por vez.
- `vram-guardian`: progressive growth + gate `before_chunk` são os disparos autoritativos de hard reclaim mid-fase (não calendário).
- `tts-fish-speech`: reuso do engine enquanto headroom seguro; EXIT mid-fase só sob sinal do guardian (ou fim da fase).
- `generate-cli`: documentar/expor override do teto opcional de residency (se mantido) e deixar claro que o default é guardian-driven.

## Impact

- Código: `workers/fish_speech.py`, `config.py`, `gpu/orchestrate.py` (`counts_against_budget`), possivelmente `gpu/lifecycle.py` / `gpu/jobs.py`, testes de worker/lifecycle, `docs/SMOKE.md`.
- Runtime: menos cold starts → TTS bem mais rápido; risco residual de pressão VRAM mid-fase mitigado pelo guardian + `GPU_PROCESS_RESERVE_MIB` (Hyprland).
- Sem mudança de formato de manifest/resume; chunks completed continuam resumíveis.
- Não altera Voice Design, LLM, chunk size (`tts_max_chunk_chars`), nem paralelismo de modelos.
