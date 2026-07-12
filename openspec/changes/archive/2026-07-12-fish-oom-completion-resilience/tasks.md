## 1. Config e JobResult

- [x] 1.1 Em `config.py`: adicionar `FISH_OOM_NO_PROGRESS_LIMIT=3`, `FISH_CHUNK_MAX_OOM_ATTEMPTS=3`; mudar default de `FISH_WORKER_RESTART_BUDGET` para `0` (desabilitado) e documentar como teto opcional
- [x] 1.2 Em `gpu/jobs.py`: adicionar campo opcional `oom_chunk_id` em `JobResult`; atualizar serialização/testes de schema se houver

## 2. Worker Fish + env do alocador

- [x] 2.1 Em `workers/fish_speech.py`: ao emitir OOM/`CONTROLLED_RESTART`, preencher `oom_chunk_id` no `JobResult`
- [x] 2.2 No spawn do Fish (`orchestrate` / lifecycle): helper que injeta `expandable_segments:True` em `PYTORCH_HIP_ALLOC_CONF` e `PYTORCH_CUDA_ALLOC_CONF` sem sobrescrever override do usuário
- [x] 2.3 Teste unitário: env merge preserva override; default aplica expandable_segments

## 3. Política de restart orientada a progresso

- [x] 3.1 Em `lifecycle.run_fish_with_restarts` (ou helper): rastrear stall consecutivo (restarts cobrados sem novo completed) e contagem OOM por `oom_chunk_id`; abortar com mensagens claras de stall / per-chunk
- [x] 3.2 Aplicar teto global `FISH_WORKER_RESTART_BUDGET` só quando >0; com `0`, não abortar por budget global
- [x] 3.3 Em `orchestrate`: passar contagem de completed / leitura de `JobResult.oom_chunk_id` para a lógica de restart; manter planned reasons sem cobrir stall
- [x] 3.4 Atualizar `tests/test_gpu_lifecycle.py`: remover expectativa de abort só por budget=8; cobrir OOM-com-progresso, stall sem progresso, e per-chunk OOM max
- [x] 3.5 Atualizar `tests/test_fish_worker.py` (e correlatos) para `oom_chunk_id` e mensagens

## 4. Docs e validação

- [x] 4.1 Atualizar `docs/SMOKE.md` (ou nota curta) sobre política de OOM/stall e alloc conf
- [x] 4.2 Rodar suite unitária relevante (`test_gpu_lifecycle`, `test_fish_worker`, jobs)
- [ ] 4.3 Smoke/resume opcional: retomar `out/classroom/7d3ef65a…` e confirmar que pending completa sem abort por budget
