## Context

Incident classroom (`7d3ef65a…`): Fish TTS chegou perto do fim e abortou com `Fish worker restart budget exhausted (8)` no chunk `ch-004-000125`. Os `result.json` dos jobs mostram `HIP out of memory` ao alocar ~200 MiB com ~1 GiB “free” no alocador PyTorch e ~420 MiB reserved-but-unallocated — fragmentação clássica — enquanto o guardian via rocm-smi ainda via ~3–4 GiB free. Cada `restart_reason=oom` consumiu o budget global; restarts `residency`/`progressive` não. O manifest ficou com chunks `pending` resumíveis, mas a fase falhou.

Hoje `LifecycleManager.run_fish_with_restarts` cobra `FISH_WORKER_RESTART_BUDGET` em todo restart não planejado e aborta ao esgotar, independentemente de o livro estar avançando.

## Goals / Non-Goals

**Goals:**

- Completar gerações longas apesar de OOMs transitórios de fragmentação HIP/CUDA.
- Abortar só quando não há progresso útil (stall) ou o mesmo chunk OOMa demais.
- Reduzir OOMs de fragmentação com `expandable_segments` no ambiente do worker Fish.
- Manter resume via manifest e lease/hard reclaim atuais.

**Non-Goals:**

- Mudar Voice Design, LLM, lease exclusivo, ou `tts_max_chunk_chars`.
- Tratar OOM como controle normal de fluxo (continua sendo `unexpected_oom`, não política saudável).
- Garantir zero OOM em ROCm; apenas resiliência + mitigação.
- Reescrever o guardian progressive/headroom (já isento de budget).

## Decisions

### D1 — Abort por stall / por-chunk, não por teto global de OOM

**Escolha:** Substituir o gate primário `restarts >= FISH_WORKER_RESTART_BUDGET` para restarts cobrados (`oom`/unknown) por:

1. **Sem progresso:** N restarts cobrados consecutivos sem nenhum SpeechChunk novo `completed` na fase → abort (`FISH_OOM_NO_PROGRESS_LIMIT`, default **3**).
2. **Por chunk:** o mesmo `chunk_id` alvo de `unexpected_oom` atinge `FISH_CHUNK_MAX_OOM_ATTEMPTS` (default **3**) → abort com diagnóstico desse id.
3. Qualquer restart cobrado após o qual o manifest ganha ≥1 completed novo **zera** o contador de stall consecutivo.

**Alternativas:** só aumentar o budget (8→∞) — mascara o problema e não protege loops; ou tratar OOM como planned reclaim — esconde falhas reais e conflita com a classificação do guardian.

`FISH_WORKER_RESTART_BUDGET` permanece como **teto de segurança opcional** (default alto ou `0` = desabilitado) para ambientes que queiram um hard cap absoluto; não é o gate primário.

### D2 — Identificar o chunk do OOM no JobResult

**Escolha:** Expor `oom_chunk_id` (opcional) em `JobResult` quando `restart_reason=oom`, preenchido pelo worker Fish (já conhece o `chunk_id` no handler). O orquestrador usa isso para o contador por-chunk sem parse de mensagem.

**Alternativa:** parsear `message` — frágil.

### D3 — `expandable_segments` no spawn do Fish worker

**Escolha:** No spawn do worker Fish, garantir env:

- Preferir `PYTORCH_HIP_ALLOC_CONF=expandable_segments:True` em ROCm.
- Também setar `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True` se ainda não definido (mensagens HIP às vezes citam a var CUDA).

Não sobrescrever se o usuário já definiu a var (merge/respeitar valor existente).

**Alternativa:** só documentar para o usuário — falha fácil de esquecer no hot path.

### D4 — OOM continua sem queimar `SPEECH_CHUNK_MAX_ATTEMPTS`

**Escolha:** Manter: OOM → chunk fica `pending`, sem `failed_chunk_id` / `mark_failed`. O novo limite por-chunk de OOM é **separado** do limite de falhas hard (`FATAL`).

### D5 — Onde implementar a lógica

**Escolha:** Contadores de stall/por-chunk em `run_fish_with_restarts` (ou helper chamado por `orchestrate.run_fish_phase`), lendo `JobResult` após cada worker exit. `has_pending` + diff de completed no manifest (já book-scoped) medem progresso.

## Risks / Trade-offs

| Risk | Mitigation |
|------|------------|
| Loop longo se OOM a cada chunk mas ainda “avança” 1 chunk | Aceitável (livro termina); cold start ~70 s/chunk no pior caso; teto opcional global permanece |
| `expandable_segments` ineficaz ou regressão em algum stack ROCm | Feature flag via env já setada; fácil desligar; logs de OOM continuam |
| Contador por-chunk perde estado entre invocações CLI | Re-run zera contadores — OK; resume completa pendings; stall aborta só dentro da mesma fase |
| Spec main ainda cita budget=3 enquanto código usa 8 + guardian change | Esta change redefine o requisito; sync/archive alinha main specs |

## Migration Plan

1. Implementar knobs + `oom_chunk_id` + lógica de stall + env no spawn.
2. Atualizar testes de lifecycle (budget esgotado → stall / per-chunk OOM).
3. Re-rodar geração classroom no mesmo out-dir (resume dos pending) para validar.
4. Rollback: restaurar charge em todo OOM contra `FISH_WORKER_RESTART_BUDGET` e remover env (git revert).

## Open Questions

- Default de `FISH_WORKER_RESTART_BUDGET` residual: `0` (off) vs valor alto (ex. 64)? Preferência: **0 = desabilitado** para não reintroduzir o abort do incident.
- Nome das vars HIP vs CUDA no ROCm do usuário — validar no smoke qual var o PyTorch ROCm honra; setar ambas é barato.
