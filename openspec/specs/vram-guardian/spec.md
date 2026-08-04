## Purpose

Política de VRAM com snapshots, thresholds configuráveis, gates antes de chunk/load, telemetria e detecção de crescimento progressivo.

## Requirements

### Requirement: Snapshots de VRAM com métricas distintas
O sistema SHALL expor um `VRAMGuardian` (ou equivalente) capaz de produzir snapshots com pelo menos: `total_mib`, `free_mib` (system-reported), e quando disponível `allocated_mib` / `reserved_mib` (PyTorch). Essas métricas MUST NÃO ser tratadas como intercambiáveis. O free do sistema é autoritativo para proteger o desktop/compositor.

#### Scenario: Snapshot antes de trabalho GPU
- **WHEN** o guardian é consultado antes de iniciar um chunk ou load de modelo
- **THEN** o snapshot inclui free do sistema e registra allocated/reserved quando o runtime PyTorch estiver disponível no processo medidor

### Requirement: Três thresholds configuráveis
A configuração central MUST definir e expor:
- `hard_floor_mib` (default 300): mínimo absoluto reservado ao sistema;
- `before_chunk_target_mib` (default 768): headroom desejado antes de um novo chunk com modelo já residente;
- `before_load_target_mib` (por backend, calibrável): headroom exigido antes de carregar/spawnar um modelo.

O load target da fase TTS MUST usar o identificador arquitetural `tts` (e/ou backend concreto `qwen3-tts` quando a calibração for específica do modelo). O default inicial de produto MUST ser **6144 MiB** free antes do load. Defaults Fish `s1-mini` **8192** / `s2-pro` **22528** e a herança implícita “valor do Fish” MUST NÃO permanecer como defaults de produto. Parler MUST manter valor de load **separado**. Um backend desconhecido MUST NÃO herdar implicitamente o load target do TTS. Defaults MUST residir em configuração centralizada. CLI e/ou env MAY sobrescrever com overrides backend-specific. Após o pipeline estável, o target MAY ser recalibrado para `peak observado + margem operacional`; o valor 6144 é margem de integração inicial (~3 GiB observados no smoke), não afirmação de consumo permanente.

#### Scenario: Defaults centralizados TTS
- **WHEN** nenhum override CLI/env é fornecido
- **THEN** o pipeline usa load target **6144 MiB** para `tts` / `qwen3-tts`

#### Scenario: Override via config
- **WHEN** o usuário define reserve/target via flag ou env suportada
- **THEN** as decisões do guardian usam os valores sobrescritos

#### Scenario: Backend desconhecido não herda TTS
- **WHEN** um backend sem default de load explícito é avaliado
- **THEN** o sistema não aplica silenciosamente o `before_load_target_mib` do TTS

### Requirement: Gate antes de chunk e antes de load
Antes de iniciar um SpeechChunk no worker, o sistema MUST verificar headroom contra `before_chunk_target_mib` (após reclaim best-effort se necessário) e MUST NÃO iniciar o chunk se `free_mib < hard_floor_mib`. Antes de spawn/load de um backend, MUST verificar `before_load_target_mib` desse backend. OOM MUST NÃO ser o mecanismo primário de controle de tamanho/work.

#### Scenario: Recusa abaixo do hard floor
- **WHEN** free VRAM está abaixo de `hard_floor_mib` antes de um novo trabalho GPU
- **THEN** o sistema não inicia esse trabalho e reporta erro com snapshot e thresholds

#### Scenario: Chunk abaixo do target após reclaim
- **WHEN** após reclaim best-effort free permanece abaixo de `before_chunk_target_mib` no MVP
- **THEN** o worker trata como inseguro (saída controlada / não inicia o chunk) em vez de forçar síntese até OOM

#### Scenario: Load bloqueado sem headroom de modelo
- **WHEN** free VRAM está abaixo de `before_load_target_mib` do backend a carregar
- **THEN** o orquestrador não spawna/carrega esse backend e falha com distinção “modelo não cabe / headroom insuficiente para load”

### Requirement: Telemetria estruturada de GPU
Fases GPU SHALL emitir logs estruturados incluindo backend, evento (`before_chunk`, `after_reclaim`, `load`, `unload`/`worker_exit`, `release_verified`/`release_failed`), chunk id quando aplicável, e métricas free/allocated/reserved quando disponíveis.

#### Scenario: Log after reclaim
- **WHEN** um reclaim entre chunks é executado
- **THEN** há registro com free_mib (e allocated/reserved se disponíveis) para aquele chunk/backend

### Requirement: Classificação de falhas de memória
Erros de política de VRAM MUST distinguir pelo menos: (1) modelo não cabe no load, (2) headroom de runtime insuficiente para o próximo chunk, (3) memória não liberada após exit/unload de worker, (4) crescimento progressivo detectado levando a restart controlado.

#### Scenario: Erro de release não verificado
- **WHEN** o worker sai mas a verificação pós-exit falha o critério de liberação
- **THEN** a mensagem/contexto identifica falha de release entre fases, não um OOM genérico de síntese

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
