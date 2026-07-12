## MODIFIED Requirements

### Requirement: Inferência Fish Speech local sem servidor HTTP
O `FishSpeechBackend` (ou o código equivalente dentro do worker Fish) MUST sintetizar áudio localmente usando as APIs Python oficiais do Fish Speech (ex.: `TTSInferenceEngine` e loaders associados). MUST NÃO usar HTTP, FastAPI, chamadas a localhost, CLI do Fish Speech como servidor, ou API cloud. O uso de **subprocess/process isolation** para executar o worker GPU sob orquestração do pipeline É permitido e É o mecanismo oficial de hard reclaim de VRAM entre fases.

#### Scenario: Síntese local sem HTTP
- **WHEN** o pipeline solicita áudio para um `TTSRequest`/SpeechChunk válido
- **THEN** a síntese ocorre localmente sem requisições de rede ao TTS e sem depender de `api_server` / URL `:8080`

#### Scenario: Worker isolado permitido
- **WHEN** o orquestrador executa a fase Fish Speech
- **THEN** a síntese MAY ocorrer em processo worker filho isolado controlado pelo LifecycleManager

### Requirement: Load e reuso do modelo dentro do worker
Os pesos MUST ser assegurados via ModelManager no máximo uma vez por necessidade de download/validação de cache por execução de geração. Dentro de uma única invocação do worker Fish, o engine GPU MUST ser reutilizado para a sequência de SpeechChunks dessa invocação sem reload completo entre chunks, enquanto o headroom permanecer seguro. O orquestrador MAY encerrar o worker e iniciar outro (reload em processo fresco) por fim de fase, degradação de VRAM, ou falha controlada. MUST NÃO exigir novo download de pesos só porque um worker encerrou.

#### Scenario: Múltiplos chunks sem reload no mesmo worker
- **WHEN** vários SpeechChunks são sintetizados na mesma invocação do worker com headroom seguro
- **THEN** a síntese completa sem novo download e sem novo load completo de pesos/engine entre esses chunks

#### Scenario: Novo worker após exit
- **WHEN** um worker Fish encerra e o orquestrador inicia outro com cache de pesos íntegro
- **THEN** o novo worker carrega o engine a partir do cache local sem reiniciar download completo

### Requirement: Liberação do engine e hard reclaim
O código Fish Speech SHALL permitir liberação best-effort do engine no processo worker (`release`/reclaim entre chunks). O hard reclaim entre fases de modelo MUST ser o exit do worker, verificado pelo orquestrador via medição de VRAM. Pesos em disco via ModelManager MUST permanecer intactos.

#### Scenario: Reclaim entre chunks é best-effort
- **WHEN** um SpeechChunk é persistido com sucesso
- **THEN** o worker executa reclaim best-effort antes do próximo chunk (sem tratar empty_cache isolado como prova de liberação total)

#### Scenario: Exit do worker é hard reclaim
- **WHEN** a fase Fish termina ou o worker faz saída controlada
- **THEN** o processo worker encerra e o orquestrador verifica a liberação de VRAM antes da próxima fase GPU

## ADDED Requirements

### Requirement: Síntese orientada a SpeechChunks no worker
A fase TTS Fish Speech MUST consumir SpeechChunks limitados (não um livro/capítulo arbitrariamente grande numa única inferência). Cada chunk sintetizado MUST ser persistido antes do reclaim e registrado para resume.

#### Scenario: Chunk limitado sintetizado e persistido
- **WHEN** o worker recebe um SpeechChunk dentro dos limites configurados
- **THEN** produz áudio não vazio, persiste o artefato, e só então reclama memória temporária
