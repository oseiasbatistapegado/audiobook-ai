## ADDED Requirements

### Requirement: Lease único de modelo GPU no orquestrador
O processo orquestrador do pipeline `generate` MUST NÃO carregar modelos GPU in-process de Voice Design ou Fish Speech. No máximo um worker GPU controlado pelo projeto MAY estar ativo por vez. O LifecycleManager SHALL conceder um lease exclusivo por fase GPU.

#### Scenario: Voice Design e Fish nunca simultâneos
- **WHEN** a fase Voice Design está em execução
- **THEN** nenhum worker Fish Speech está ativo, e reciprocamente

#### Scenario: Orquestrador sem engine residente
- **WHEN** o orquestrador conclui uma fase GPU (worker exit)
- **THEN** o processo orquestrador não mantém referências a engines/modelos GPU carregados dessa fase

### Requirement: Workers isolados como hard reclaim oficial
Voice Design e Fish Speech MUST executar em processos worker isolados. O encerramento (exit) do worker SHALL ser o mecanismo oficial de hard reclaim de VRAM entre fases de modelo. Unload apenas in-process MUST NÃO ser tratado como prova suficiente de liberação no hot path do produto sob ROCm.

#### Scenario: Exit do Voice Design libera lease
- **WHEN** o worker de Voice Design termina e o LifecycleManager verifica a liberação
- **THEN** a fase é considerada concluída somente se a VRAM medida satisfizer a política de release verificada

#### Scenario: Exit do Fish Speech libera lease
- **WHEN** o worker Fish Speech termina (sucesso ou saída controlada)
- **THEN** o orquestrador verifica liberação de VRAM antes de iniciar outra fase GPU ou declarar a fase TTS concluída

### Requirement: Fish worker processa sequência limitada de chunks
O worker Fish Speech MUST carregar o modelo no máximo uma vez por invocação do worker, processar uma sequência de SpeechChunks pendentes, e MUST NÃO ser spawnado uma vez por SpeechChunk sob operação normal.

#### Scenario: Múltiplos chunks no mesmo worker
- **WHEN** há N>1 SpeechChunks pendentes e o headroom permanece seguro
- **THEN** um único worker carrega o engine uma vez e sintetiza esses chunks em sequência

#### Scenario: Restart controlado sob degradação
- **WHEN** o worker detecta headroom insuficiente após reclaim ou crescimento progressivo de memória
- **THEN** o worker encerra de forma controlada sem sintetizar o próximo chunk inseguro, e o orquestrador MAY iniciar um worker fresco para continuar a partir do manifest

### Requirement: Budget de restart do Fish worker e por chunk
O orquestrador MUST limitar restarts controlados do Fish worker a um default de **3** por geração (excluindo o worker inicial). Cada restart por degradação de VRAM consome esse budget. O mesmo `SpeechChunk` MUST ter no máximo **2** tentativas totais (primeira + 1 retry); se falhar de novo, o pipeline MUST abortar com contexto diagnóstico. Unexpected OOM MUST NÃO causar retries automáticos unbounded. Ambos os limites MUST ser configuráveis.

#### Scenario: Terceiro restart controlado ainda permitido
- **WHEN** já ocorreram 2 restarts controlados e o worker pede o terceiro com chunks pendentes
- **THEN** o orquestrador spawna mais um worker fresco dentro do budget default

#### Scenario: Quarto restart controlado recusado
- **WHEN** o budget default de 3 restarts já foi consumido e outro `controlled_restart_needed` ocorre
- **THEN** o pipeline falha com contexto de budget esgotado em vez de spawnar indefinidamente

#### Scenario: Segunda falha no mesmo chunk aborta
- **WHEN** o mesmo SpeechChunk id falha duas vezes
- **THEN** o pipeline falha com diagnóstico do chunk e NÃO continua reiniciando workers só por esse id

### Requirement: Job directory versionado como IPC canônico
A comunicação autoritativa orquestrador↔worker MUST usar um job directory sob o work-dir book-scoped. O worker recebe o path do job; progresso durável passa por arquivos/manifest. stdout/stderr MAY carregar logs, mas MUST NÃO ser o canal autoritativo de estado. Arquivos de job MUST ser versionados e escritos atomicamente.

#### Scenario: Progresso sobrevive ao crash do worker
- **WHEN** um worker Fish crasha após persistir um chunk e atualizar o manifest
- **THEN** o orquestrador consegue retomar a partir dos arquivos do job/manifest sem depender do stdout do processo morto

### Requirement: Transição entre modelos só com release verificado
Antes de carregar o próximo modelo GPU (spawn do próximo worker), o LifecycleManager MUST medir VRAM e MUST recusar a transição se a liberação do worker anterior não atingir o critério configurado (`before_load_target` do próximo backend e/ou hard floor conforme política).

#### Scenario: Falha segura se VRAM não liberou
- **WHEN** o worker anterior saiu mas free VRAM permanece abaixo do target de load do próximo backend
- **THEN** o pipeline falha com erro contextual distinguindo “memória não liberada” e NÃO spawna o próximo worker GPU

### Requirement: Ollama permanece fora do lease in-process
O LLM via Ollama (processo externo) MUST continuar a ser descarregado antes da fase Fish Speech quando aplicável. Ollama NÃO conta como “modelo GPU in-process” do lease, mas o pipeline MUST evitar overlapping intencional de VRAM com workers GPU.

#### Scenario: Unload Ollama antes do Fish worker
- **WHEN** o pipeline vai spawnar o worker Fish Speech após interpret remoto
- **THEN** Ollama foi unloaded (ou não houve chamada remota) antes do spawn
