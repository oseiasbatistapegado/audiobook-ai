## Why

Em livros longos o Fish worker aborta a geração com `Fish worker restart budget exhausted` mesmo com progresso quase completo — ex.: classroom ficou com 125/136+ chunks done e parou em `ch-004-000125`. O HIP reporta OOM por fragmentação do alocador (~200 MiB contíguos) enquanto o guardian ainda vê ~3–4 GiB free; cada `unexpected_oom` consome o budget global e a geração desiste com chunks `pending` recuperáveis. O produto precisa terminar o livro (resume via manifest) em vez de falhar por teto absoluto de restarts.

## What Changes

- Trocar a política de abort por **budget global de OOM** por uma política **orientada a progresso**: restarts por `unexpected_oom` continuam permitidos enquanto a geração avança (novos chunks `completed` entre restarts).
- Abortar só quando não há progresso útil: o mesmo `SpeechChunk` estoura OOM repetidamente sem completar, ou N restarts consecutivos sem nenhum chunk novo completed.
- Mitigar a causa raiz de fragmentação no worker Fish: aplicar `expandable_segments` (HIP/CUDA alloc conf) no ambiente do worker no spawn.
- Manter restarts planejados (`progressive` / `headroom` / `residency`) fora do contador de falha; manter hard `FATAL` (não-OOM) com limite por chunk.
- Garantir que re-execução no mesmo book-dir continue dos `pending` até merge, sem exigir limpeza manual após abort por OOM.

## Capabilities

### New Capabilities

- (nenhuma)

### Modified Capabilities

- `gpu-lifecycle`: política de restart/abort do Fish passa de teto global fixo de OOM para gates por progresso / por-chunk; documentar quando o pipeline MAY continuar vs MUST abortar.
- `tts-fish-speech`: worker Fish MUST receber config de alocador com `expandable_segments` para reduzir OOM por fragmentação mid-fase.

## Impact

- Código: `config.py`, `gpu/lifecycle.py`, `gpu/orchestrate.py`, `gpu/jobs.py` (se classificação de budget mudar), spawn/env do Fish worker, testes (`test_gpu_lifecycle.py`, `test_fish_worker.py`), docs/SMOKE se mencionar budget=3/8.
- Runtime: gerações longas devem concluir apesar de OOMs transitórios de fragmentação; risco de loop infinito mitigado por “sem progresso” + teto por chunk.
- Manifest/resume: sem mudança de formato; chunks já `completed` permanecem; `pending` são retentados.
- Não altera Voice Design, LLM, lease exclusivo, nem tamanho default de chunk (`tts_max_chunk_chars`).
