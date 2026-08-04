## ADDED Requirements

### Requirement: Configuração de multi-worker TTS
O sistema SHALL expor uma configuração `TTS_MULTI_WORKER_COUNT` (env var ou CLI flag `--tts-multi-workers`) que define o número de workers TTS paralelos. Default é **2**. Valor máximo é **4**. Valor **1** desabilita multi-worker e restaura o comportamento de worker único.

#### Scenario: Default 2 workers
- **WHEN** nenhuma configuração é fornecida
- **THEN** o pipeline spawna 2 workers TTS em paralelo

#### Scenario: Configuração via env var
- **WHEN** `TTS_MULTI_WORKER_COUNT=4` é definida
- **THEN** o pipeline spawna 4 workers TTS em paralelo

#### Scenario: Valor máximo respeitado
- **WHEN** `TTS_MULTI_WORKER_COUNT=8` é definido
- **THEN** o pipeline ajusta para 4 workers e emite warning de cap

#### Scenario: Valor 1 desabilita multi-worker
- **WHEN** `TTS_MULTI_WORKER_COUNT=1` é definido
- **THEN** o pipeline opera com worker único (comportamento atual)

### Requirement: Distribuição round-robin por voice_id
Os chunks TTS SHALL ser distribuídos entre workers via `voice_id % worker_count` (hash determinístico). O mesmo `voice_id` sempre vai ao mesmo worker. O orquestrador calcula a distribuição antes de iniciar a fase TTS.

#### Scenario: Mesma voz sempre no mesmo worker
- **WHEN** dois chunks com `voice_id=42` são processados com 3 workers
- **THEN** ambos os chunks vão para o worker `42 % 3 = 0`

#### Scenario: Distribuição balanceada
- **WHEN** 100 chunks com 10 `voice_id`s distintos são distribuídos com 2 workers
- **THEN** cada worker recebe ~50 chunks (±10%)

### Requirement: Job directory isolado por worker
Cada worker TTS SHALL escrever seus outputs em um subdiretório `jobs/tts_worker_{i}/` onde `i` é o index do worker (0-based). Cada job dir contém os chunks processados pelo worker e uma entrada no manifest consolidado.

#### Scenario: Worker 0 escreve em job_dir próprio
- **WHEN** o worker 0 sintetiza um chunk
- **THEN** o audio é salvo em `jobs/tts_worker_0/<chunk_id>.wav`

#### Scenario: Manifest consolidado tem worker_id
- **WHEN** o manifest é atualizado por um worker
- **THEN** a entrada do chunk inclui `worker_id: <i>`

### Requirement: VRAMGuardian por worker
Cada worker TTS SHALL ter seu próprio `VRAMGuardian` independente. O orquestrador calcula `before_multi_worker_load_mib` = `worker_count × (per_worker_vram + 200 MB margin)` antes de spawnar workers.

#### Scenario: Headroom total verificado antes do spawn
- **WHEN** `TTS_MULTI_WORKER_COUNT=2`
- **THEN** free VRAM >= 2 × (2800 MB + 200 MB) = 6000 MB é verificado antes de spawnar qualquer worker

#### Scenario: Worker com VRAM insuficiente não é spawnado
- **WHEN** free VRAM < `before_multi_worker_load_mib` antes do spawn
- **THEN** o pipeline reduz `TTS_MULTI_WORKER_COUNT` ou falha com erro contextual

### Requirement: Merge final a partir de manifest multi-worker
O merge final SHALL ler o manifest consolidado, ordenar chunks por `chunk_order` (não por `worker_id`), e concatenar os arquivos de áudio em sequência. O campo `worker_id` é ignorado no merge.

#### Scenario: Merge ordena por chunk_order
- **WHEN** chunks de 2 workers estão no manifest com `chunk_order` de 0 a 99 intercalados
- **THEN** o merge concatena na ordem `chunk_order` 0, 1, 2, ..., 99

#### Scenario: Worker crashado não impede merge
- **WHEN** worker 1 crasha e chunks dele estão faltando no filesystem
- **THEN** o merge sinaliza chunks faltantes e o pipeline retoma com worker fresco

### Requirement: Resume com multi-worker
O pipeline SHALL resumir a partir do manifest consolidado. Workers novos processam apenas chunks faltantes. Worker antigo que crashou é substituído por um novo worker com o mesmo index (reutiliza o job dir).

#### Scenario: Resume ignora chunks já completed
- **WHEN** o manifest lista 50 chunks como `completed` e o pipeline retoma
- **THEN** workers novos processam apenas os 50 chunks restantes

#### Scenario: Worker recriado reutiliza job dir
- **WHEN** worker 1 crasha e é substituído por worker 1'
- **THEN** worker 1' escreve em `jobs/tts_worker_1/` (mesmo dir)

### Requirement: Telemetria com worker_id
Todos os logs estruturados da fase TTS SHALL incluir `worker_id` no contexto. O orquestrador SHALL logar progresso agregado (total chunks, chunks por worker) a cada N chunks.

#### Scenario: Log de chunk inclui worker_id
- **WHEN** um worker sintetiza um chunk com sucesso
- **THEN** o log inclui `worker_id: 0` (ou o index correspondente)

#### Scenario: Progresso agregado é logado
- **WHEN** 10 chunks são completados na fase TTS
- **THEN** o log mostra `progress: 10/100 (worker_0: 4, worker_1: 6)`

## MODIFIED Requirements

### Requirement: Load e reuso do modelo dentro do worker TTS (modificado)
**De:** "O orquestrador MUST preferir uma fase TTS contínua com worker residente"
**Para:** "O orquestrador spawna N workers residentes, cada um com seu próprio modelo Qwen3-TTS carregado. Cada worker processa chunks atribuídos e reutiliza o engine durante sua sessão. O orquestrador monitora todos os workers simultaneamente."

#### Scenario: N workers carregam modelos independentemente
- **WHEN** `TTS_MULTI_WORKER_COUNT=2`
- **THEN** 2 processos separados carregam o modelo Qwen3-TTS, cada um com ~2.8 GB de VRAM

### Requirement: Batching e overlap oficiais quando disponíveis (modificado)
**De:** "O worker MUST usar batching/multi-request suportado pela API oficial do Qwen3-TTS quando disponível"
**Para:** "Além do batching intra-worker, o sistema multiplexa N workers paralelos. O batch size por worker é configurável via `TTS_SAME_VOICE_BATCH_SIZE` (default 8). O orquestrador coordena a distribuição de chunks entre workers."

#### Scenario: Batch size aumentado
- **WHEN** `TTS_SAME_VOICE_BATCH_SIZE=8`
- **THEN** cada worker processa até 8 chunks da mesma voz por batch de inferência

## REMOVED Requirements

### Requirement: Lease único de modelo GPU no orquestrador (modificado)
**De:** "No máximo um worker GPU controlado pelo projeto MAY estar ativo por vez."
**Para:** "No máximo um worker GPU por fase/backend está ativo, exceto para TTS onde N workers paralelos MAY estar ativos simultaneamente sob controle do `TTS_MULTI_WORKER_COUNT`."

#### Scenario: N workers TTS simultâneos
- **WHEN** `TTS_MULTI_WORKER_COUNT=2`
- **THEN** 2 workers TTS estão ativos simultaneamente, ambos com lease do LifecycleManager
