## ADDED Requirements

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

O default inicial de load para Fish Speech MUST ser **22528 MiB** free (valor conservador derivado do spike RX 7900 XTX, não requisito universal). Parler MUST ter valor de load **separado** e calibrado; um backend desconhecido MUST NÃO herdar implicitamente o valor do Fish. Defaults MUST residir em configuração centralizada e MUST NÃO ser duplicados como magic numbers nos backends. CLI e/ou variáveis de ambiente MAY sobrescrever esses valores com overrides backend-specific.

#### Scenario: Defaults centralizados
- **WHEN** nenhum override CLI/env é fornecido
- **THEN** o pipeline usa os defaults centralizados de hard floor, chunk target e Fish load target 22528 MiB

#### Scenario: Override via config
- **WHEN** o usuário define reserve/target via flag ou env suportada
- **THEN** as decisões do guardian usam os valores sobrescritos

#### Scenario: Backend desconhecido não herda Fish
- **WHEN** um backend sem default de load explícito é avaliado
- **THEN** o sistema não aplica silenciosamente o `before_load_target_mib` do Fish Speech
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
Após cada SpeechChunk bem-sucedido, o sistema MUST registrar o system free VRAM pós-reclaim. Com janela configurável das últimas `K` amostras (default **3**) e limiar `N` MiB (default **256**), o worker MUST emitir saída `controlled_restart_needed` quando free cair pelo menos `N` MiB ao longo da janela e a tendência for monotonicamente ou consistentemente descendente. Um único sample anômalo MUST NÃO disparar restart. Independente da tendência, se o próximo chunk não satisfizer `before_chunk_target_mib` após reclaim, o worker MUST reiniciar de forma controlada. O sistema MUST NÃO esperar violar `hard_floor_mib` nem OOM para considerar degradação.

#### Scenario: Tendência sustentada dispara restart
- **WHEN** as últimas K amostras pós-reclaim mostram queda acumulada ≥ N MiB com tendência descendente consistente
- **THEN** o worker encerra com `controlled_restart_needed` sem sintetizar o próximo chunk

#### Scenario: Sample isolado não reinicia
- **WHEN** uma única amostra pós-reclaim cai mas a janela não satisfaz queda ≥ N com tendência consistente
- **THEN** o worker não dispara restart só por esse sample

#### Scenario: Target de chunk força restart imediato
- **WHEN** após reclaim o próximo chunk não atinge `before_chunk_target_mib`
- **THEN** o worker faz saída controlada imediatamente, mesmo sem tendência completa na janela

### Requirement: Detecção de crescimento progressivo por janela deslizante
Após cada SpeechChunk bem-sucedido, o sistema MUST registrar o system free VRAM pós-reclaim. Com janela configurável das últimas `K` amostras (default **3**) e limiar `N` MiB (default **256**), o worker MUST emitir saída `controlled_restart_needed` quando free cair pelo menos `N` MiB ao longo da janela e a tendência for monotonicamente ou consistentemente descendente. Um único sample anômalo MUST NÃO disparar restart. Independente da tendência, se o próximo chunk não satisfizer `before_chunk_target_mib` após reclaim, o worker MUST reiniciar de forma controlada. O sistema MUST NÃO esperar violar `hard_floor_mib` nem OOM para considerar degradação.

#### Scenario: Tendência sustentada dispara restart
- **WHEN** as últimas K amostras pós-reclaim mostram queda acumulada ≥ N MiB com tendência descendente consistente
- **THEN** o worker encerra com `controlled_restart_needed` sem sintetizar o próximo chunk

#### Scenario: Sample isolado não reinicia
- **WHEN** uma única amostra pós-reclaim cai mas a janela não satisfaz queda ≥ N com tendência consistente
- **THEN** o worker não dispara restart só por esse sample

#### Scenario: Target de chunk força restart imediato
- **WHEN** após reclaim o próximo chunk não atinge `before_chunk_target_mib`
- **THEN** o worker faz saída controlada imediatamente, mesmo sem tendência completa na janela
