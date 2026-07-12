## Context

Na RX 7900 XTX / ROCm / Hyprland, hard reclaim de VRAM do Fish Speech só é fiável via **exit do processo worker**. O soft-cap `FISH_CHUNKS_PER_WORKER=2` força esse exit a cada dois chunks mesmo com free estável, impondo ~70 s de cold load por ciclo e dominando o wall-time do TTS.

O `VRAMGuardian` já implementa:
- gate `before_chunk` (`before_chunk_target_mib` / `hard_floor_mib`);
- progressive growth (janela K/N pós-reclaim).

Constraint inalterável: **no máximo um modelo GPU do projeto ativo por vez** (Parler XOR Fish; Ollama unloaded antes do Fish).

## Goals / Non-Goals

**Goals:**
- Fish permanece residente na mesma invocação do worker enquanto o guardian considerar headroom seguro.
- Hard reclaim mid-fase só por sinal do guardian (progressive / headroom) ou fim da fase (sem pending).
- Restarts de reclaim saudável (progressive, headroom; e teto opcional) NÃO consomem `FISH_WORKER_RESTART_BUDGET`.
- Preservar estabilidade do Hyprland e lease exclusivo de um modelo.

**Non-Goals:**
- Aumentar `tts_max_chunk_chars` ou recalibrar thresholds K/N / floor (podem ser changes separados).
- Manter Fish carregado através de fases LLM/Parler (viola um-modelo-por-vez).
- Inferência Fish em CPU / multi-GPU / paralelismo.
- Mudar formato de manifest ou contrato de resume.

## Decisions

### D1 — Política primária = guardian, não calendário
**Escolha:** Remover o EXIT automático por contagem de chunks como default. O worker só emite `CONTROLLED_RESTART_NEEDED` mid-fase quando:
1. `record_post_reclaim` indica progressive growth, ou
2. o próximo chunk falha `can_start_chunk` após reclaim (`restart_reason=headroom`), ou
3. (opcional) teto de segurança explícito está habilitado e foi atingido.

**Alternativa rejeitada:** Manter residency=2 e só “tunar” para 4/8 — ainda é calendário, não o pedido.

### D2 — Teto opcional desligado por default
**Escolha:** `FISH_CHUNKS_PER_WORKER` default **0** = desabilitado. Valor >0 reativa o soft-cap antigo como escape hatch (CLI/env/config).

**Alternativa rejeitada:** Default alto (ex. 64) — ainda mascara falhas do guardian e reintroduz cold starts desnecessários.

### D3 — Budget só para reclaim “não saudável”
**Escolha:** `counts_against_budget` retorna false para `restart_reason` in `{progressive, headroom, residency}`. Continua true para `oom` e razões desconhecidas/FATAL path.

**Rationale:** Em livros longos, progressive pode disparar dezenas de vezes; budget 8 abortaria gerações saudáveis. Progressive/headroom *são* o mecanismo normal de reclaim nesta change.

**Alternativa rejeitada:** Subir budget para milhares — menos claro semanticamente que “reclaim planejado não conta”.

### D4 — Um modelo por vez permanece no LifecycleManager
**Escolha:** Sem mudança de arquitetura de lease. Entre capítulos o pipeline continua: release Fish → interpret (Ollama) → Parler se necessário → Fish. Esta change só alonga a vida do worker **dentro** da fase Fish de uma leva de chunks pendentes.

### D5 — Telemetria
**Escolha:** Logs `[gpu] event=controlled_restart` já existentes; mensagem/progresso Rich distinguem `progressive` / `headroom` / `residency` (teto). Sem novo schema de job além de `restart_reason` já versionado.

## Risks / Trade-offs

| Risk | Mitigation |
|------|------------|
| Progressive growth não dispara a tempo → OOM mid-synth | `GPU_PROCESS_RESERVE_MIB` continua; OOM → controlled restart; smoke multi-chunk longo (≥20 chunks) na 7900 XTX |
| Falsos positivos de progressive → reloads extras | K/N já calibrados (3/256); sample isolado não reinicia |
| Livro inteiro num worker → fragmentação extrema | Guardian + OOM path; teto opcional reativável |
| Hyprland sob dips transitórios mid-synth | Aceito como residual risk do design anterior; não baixar reserve |
| Testes/docs assumem residency=2 | Atualizar unitários + SMOKE |

## Migration Plan

1. Implementar + testes unitários (fake guardian força progressive após N chunks; sem progressive não há EXIT por contagem).
2. Smoke local: ≥20 SpeechChunks, Hyprland estável, cold starts só sob `restart_reason` guardian (ou fim de fase).
3. Rollback: `AUDIOBOOK_AI_FISH_CHUNKS_PER_WORKER=2` (ou config) restaura comportamento antigo.

## Open Questions

Nenhum bloqueante. Calibração fina de K/N pós-smoke desta change MAY ajustar defaults numa follow-up se progressive disparar demais ou de menos.
