## MODIFIED Requirements

### Requirement: Detecção de crescimento progressivo por janela deslizante
Após cada SpeechChunk bem-sucedido, o sistema MUST registrar métricas pós-reclaim (`free_mib` e, quando disponíveis, `allocated_mib` / `reserved_mib`). O worker MUST emitir `controlled_restart_needed` por crescimento progressivo somente quando houver **pressão real de memória**, definida por pelo menos um de: (1) `allocated_mib` e/ou `reserved_mib` crescendo de forma persistente ao longo da janela configurável; (2) `free_mib` aproximando-se de `hard_floor_mib` (dentro de uma margem configurável). Uma queda absoluta isolada de `free_mib` com `allocated_mib`/`reserved_mib` estáveis e `free_mib` muito acima do hard floor MUST NÃO disparar restart. Um único sample anômalo MUST NÃO disparar restart. Independente da tendência, se o próximo chunk não satisfizer `before_chunk_target_mib` após reclaim, o worker MUST reiniciar de forma controlada. OOM real, stall e ausência de progresso permanecem protegidos.

#### Scenario: Free cai com allocated estável e folga grande — sem restart
- **WHEN** as últimas K amostras mostram queda de `free_mib` ≥ N MiB mas `allocated_mib`/`reserved_mib` estão estáveis e `free_mib` permanece muito acima de `hard_floor_mib`
- **THEN** o worker NÃO emite `controlled_restart_needed` por progressive growth

#### Scenario: Allocated cresce persistentemente — restart
- **WHEN** as últimas K amostras pós-reclaim mostram crescimento persistente de `allocated_mib` e/ou `reserved_mib`
- **THEN** o worker encerra com `controlled_restart_needed` sem sintetizar o próximo chunk

#### Scenario: Free aproxima hard floor — restart
- **WHEN** `free_mib` pós-reclaim entra na margem configurável do `hard_floor_mib`
- **THEN** o worker faz saída controlada por pressão real de memória

#### Scenario: Sample isolado não reinicia
- **WHEN** uma única amostra pós-reclaim é anômala mas a janela não satisfaz pressão real persistente
- **THEN** o worker não dispara restart só por esse sample

#### Scenario: Target de chunk força restart imediato
- **WHEN** após reclaim o próximo chunk não atinge `before_chunk_target_mib`
- **THEN** o worker faz saída controlada imediatamente, mesmo sem tendência completa na janela

#### Scenario: Headroom estável permite continuar residente
- **WHEN** após vários chunks o free pós-reclaim permanece acima de `before_chunk_target_mib` e não há pressão real (allocated/reserved estáveis, free longe do floor)
- **THEN** o guardian NÃO exige hard reclaim e o worker MAY continuar sintetizando na mesma invocação
