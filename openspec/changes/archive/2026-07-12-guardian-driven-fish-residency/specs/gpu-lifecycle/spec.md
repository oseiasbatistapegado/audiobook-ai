## MODIFIED Requirements

### Requirement: Fish worker processa sequência limitada de chunks
O worker Fish Speech MUST carregar o modelo no máximo uma vez por invocação do worker e processar a sequência de SpeechChunks pendentes dessa invocação. MUST NÃO ser spawnado uma vez por SpeechChunk sob operação normal. O worker MUST permanecer residente e continuar sintetizando enquanto o `VRAMGuardian` considerar o headroom seguro. Hard reclaim mid-fase (EXIT com `controlled_restart_needed`) MUST ocorrer quando o guardian sinalizar degradação de free VRAM (crescimento progressivo pós-reclaim e/ou falha do gate `before_chunk` após reclaim). MUST NÃO encerrar só por contagem fixa de chunks quando o teto opcional de residency estiver desabilitado (default).

#### Scenario: Múltiplos chunks no mesmo worker com headroom seguro
- **WHEN** há N>1 SpeechChunks pendentes e o guardian não sinaliza degradação de free VRAM
- **THEN** um único worker carrega o engine uma vez e sintetiza esses chunks em sequência sem EXIT por calendário

#### Scenario: Restart controlado sob degradação do guardian
- **WHEN** o worker detecta headroom insuficiente após reclaim ou crescimento progressivo de memória
- **THEN** o worker encerra de forma controlada sem sintetizar o próximo chunk inseguro, e o orquestrador MAY iniciar um worker fresco para continuar a partir do manifest

#### Scenario: Sem restart por calendário com teto desabilitado
- **WHEN** o teto opcional de residency está desabilitado e o guardian não sinaliza degradação após vários chunks
- **THEN** o worker NÃO emite `controlled_restart_needed` apenas porque atingiu um número fixo de chunks

### Requirement: Budget de restart do Fish worker e por chunk
O orquestrador MUST limitar restarts controlados do Fish worker que consomem budget a um default configurável (excluindo o worker inicial). Restarts de reclaim planejado disparados pelo guardian (`restart_reason` progressive ou headroom) e o teto opcional de residency (`residency`) MUST NÃO consumir esse budget. Restarts por OOM inesperado / razões não planejadas MUST consumir o budget. O mesmo `SpeechChunk` MUST ter no máximo **2** tentativas totais (primeira + 1 retry) para falhas hard (`FATAL` com `failed_chunk_id`); se falhar de novo, o pipeline MUST abortar com contexto diagnóstico. Unexpected OOM MUST NÃO causar retries automáticos unbounded. Ambos os limites MUST ser configuráveis.

#### Scenario: Restart progressive não consome budget
- **WHEN** o worker encerra com `controlled_restart_needed` e `restart_reason=progressive` com chunks pendentes
- **THEN** o orquestrador spawna um worker fresco sem incrementar o contador de budget de restarts

#### Scenario: Restart headroom não consome budget
- **WHEN** o worker encerra com `controlled_restart_needed` e `restart_reason=headroom` com chunks pendentes
- **THEN** o orquestrador spawna um worker fresco sem incrementar o contador de budget de restarts

#### Scenario: OOM consome budget até esgotar
- **WHEN** restarts por OOM/não planejados esgotam o budget configurado e outro restart cobrado ocorre
- **THEN** o pipeline falha com contexto de budget esgotado em vez de spawnar indefinidamente

#### Scenario: Segunda falha no mesmo chunk aborta
- **WHEN** o mesmo SpeechChunk id falha duas vezes com falha hard
- **THEN** o pipeline falha com diagnóstico do chunk e NÃO continua reiniciando workers só por esse id

## ADDED Requirements

### Requirement: Teto opcional de residency como escape hatch
A configuração MAY expor um teto opcional de chunks por invocação do worker Fish (`FISH_CHUNKS_PER_WORKER` ou equivalente). Default MUST ser desabilitado (sem EXIT por contagem). Quando habilitado com valor >0, ao atingir o teto com chunks ainda pendentes o worker MUST encerrar com `controlled_restart_needed` e `restart_reason=residency` (sem consumir budget), permitindo rollback operacional ao comportamento antigo.

#### Scenario: Teto desabilitado por default
- **WHEN** nenhum override habilita o teto de residency
- **THEN** o worker não encerra só por contagem de chunks completados na invocação

#### Scenario: Teto habilitado força reclaim
- **WHEN** o teto está configurado para N>0 e o worker completa N chunks com mais pendentes
- **THEN** o worker emite `controlled_restart_needed` com `restart_reason=residency`
