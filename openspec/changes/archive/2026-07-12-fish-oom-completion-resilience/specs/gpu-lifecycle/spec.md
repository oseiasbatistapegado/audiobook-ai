## MODIFIED Requirements

### Requirement: Budget de restart do Fish worker e por chunk
O orquestrador MUST permitir restarts controlados do Fish worker enquanto a geração fizer progresso útil, em vez de abortar por um teto global fixo de restarts por OOM. Restarts de reclaim planejado (`restart_reason` progressive, headroom ou residency) MUST NÃO contar como falha de progresso nem consumir tetos de OOM. Restarts por OOM inesperado / razões não planejadas MUST:

1. Continuar (spawn de worker fresco) enquanto chunks permanecerem pendentes e houver progresso (pelo menos um SpeechChunk novo `completed` desde o último restart cobrado zera o contador de stall).
2. Abortar quando ocorrerem `FISH_OOM_NO_PROGRESS_LIMIT` (default **3**) restarts cobrados **consecutivos** sem nenhum chunk novo completed.
3. Abortar quando o mesmo `SpeechChunk` id for alvo de `unexpected_oom` `FISH_CHUNK_MAX_OOM_ATTEMPTS` (default **3**) vezes na mesma fase de geração.

Um teto global absoluto (`FISH_WORKER_RESTART_BUDGET`) MAY existir como escape hatch; default MUST ser desabilitado (`0`). O mesmo `SpeechChunk` MUST ter no máximo **2** tentativas totais (primeira + 1 retry) para falhas hard (`FATAL` com `failed_chunk_id`); se falhar de novo, o pipeline MUST abortar com contexto diagnóstico. Unexpected OOM MUST NÃO queimar essas tentativas hard nem causar retries unbounded sem os gates de stall/por-chunk acima. Todos os limites MUST ser configuráveis. Quando `restart_reason=oom`, o `JobResult` MUST incluir `oom_chunk_id` identificando o chunk que disparou o OOM.

#### Scenario: OOM com progresso continua
- **WHEN** um worker encerra com `unexpected_oom` / `restart_reason=oom`, chunks pendentes restam, e após restarts anteriores a fase já completou pelo menos um chunk novo desde o último OOM
- **THEN** o orquestrador spawna um worker fresco e NÃO aborta só porque o número acumulado de OOMs na geração é alto

#### Scenario: Stall sem progresso aborta
- **WHEN** ocorrem N=`FISH_OOM_NO_PROGRESS_LIMIT` restarts cobrados consecutivos sem nenhum SpeechChunk novo completed
- **THEN** o pipeline falha com contexto de stall/OOM sem progresso em vez de spawnar indefinidamente

#### Scenario: Mesmo chunk OOM demais aborta
- **WHEN** o mesmo `oom_chunk_id` atinge `FISH_CHUNK_MAX_OOM_ATTEMPTS` OOMs na fase
- **THEN** o pipeline falha com diagnóstico desse chunk id e NÃO continua reiniciando só por esse id

#### Scenario: Restart progressive não conta como stall
- **WHEN** o worker encerra com `controlled_restart_needed` e `restart_reason=progressive` com chunks pendentes
- **THEN** o orquestrador spawna um worker fresco sem incrementar contadores de OOM/stall

#### Scenario: Segunda falha hard no mesmo chunk aborta
- **WHEN** o mesmo SpeechChunk id falha duas vezes com falha hard (`FATAL`)
- **THEN** o pipeline falha com diagnóstico do chunk e NÃO continua reiniciando workers só por esse id

#### Scenario: Teto global desabilitado por default
- **WHEN** `FISH_WORKER_RESTART_BUDGET` está desabilitado (default)
- **THEN** o orquestrador NÃO aborta por esgotamento de budget global de restarts
