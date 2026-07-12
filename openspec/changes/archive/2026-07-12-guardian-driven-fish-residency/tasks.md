## 1. Config e contrato de restart

- [x] 1.1 Alterar `FISH_CHUNKS_PER_WORKER` default para `0` (desabilitado) e documentar semântica: `>0` = teto opcional
- [x] 1.2 Atualizar `counts_against_budget` em `gpu/orchestrate.py` para NÃO cobrar `progressive` nem `headroom` (além de `residency`)
- [x] 1.3 Ajustar mensagens/logs de controlled restart para distinguir reclaim guardian vs teto vs OOM

## 2. Worker Fish guardian-driven

- [x] 2.1 Remover EXIT por calendário quando `FISH_CHUNKS_PER_WORKER <= 0` em `workers/fish_speech.py`
- [x] 2.2 Manter EXIT por progressive growth e por falha de `can_start_chunk`/headroom após reclaim
- [x] 2.3 Quando teto `>0` estiver habilitado, preservar EXIT com `restart_reason=residency` ao atingir N chunks com pending

## 3. CLI / env

- [x] 3.1 Expor override `--fish-chunks-per-worker` e/ou `AUDIOBOOK_AI_FISH_CHUNKS_PER_WORKER` na CLI `generate`, plumb até config/job
- [x] 3.2 Garantir que help/docs deixam claro: default = guardian-driven; teto é escape hatch

## 4. Testes

- [x] 4.1 Unitário: com teto desabilitado e guardian estável, worker processa >2 chunks sem `restart_reason=residency`
- [x] 4.2 Unitário: progressive growth dispara `controlled_restart_needed` e orquestrador reinicia sem consumir budget
- [x] 4.3 Unitário: `restart_reason=headroom` também não consome budget; `oom` consome
- [x] 4.4 Unitário: teto `N>0` ainda força residency restart (escape hatch)
- [x] 4.5 Atualizar testes existentes que assumem residency=2

## 5. Docs e smoke

- [x] 5.1 Atualizar `docs/SMOKE.md` (e comentários em `config.py`) para política guardian-driven + teto opcional
- [ ] 5.2 Smoke multi-chunk (≥20 chunks) na 7900 XTX: Hyprland estável; cold starts só sob progressive/headroom/fim de fase (ou teto se habilitado)
