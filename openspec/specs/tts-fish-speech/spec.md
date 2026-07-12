## Purpose

Interface `TTSBackend` pluggable com implementação Fish Speech local (worker isolado sob LifecycleManager) para síntese de áudio.

## Requirements

### Requirement: Interface TTSBackend pluggable
O sistema SHALL expor uma interface `TTSBackend` com API única de síntese (ex.: `synthesize(TTSRequest) -> AudioSegment`). Backends TTS MUST NÃO depender de implementações LLM ou extractors. Adicionar um novo backend no futuro MUST exigir apenas nova implementação + registro no factory.

#### Scenario: Factory resolve Fish Speech
- **WHEN** a configuração/pipeline solicita o backend `fish-speech`
- **THEN** o factory retorna uma instância de `FishSpeechBackend` que implementa `TTSBackend`

### Requirement: Inferência Fish Speech local sem servidor HTTP
O `FishSpeechBackend` (ou o código equivalente dentro do worker Fish) MUST sintetizar áudio localmente usando as APIs Python oficiais do Fish Speech (ex.: `TTSInferenceEngine` e loaders associados). MUST NÃO usar HTTP, FastAPI, chamadas a localhost, CLI do Fish Speech como servidor, ou API cloud. O uso de **subprocess/process isolation** para executar o worker GPU sob orquestração do pipeline É permitido e É o mecanismo oficial de hard reclaim de VRAM entre fases.

#### Scenario: Síntese local sem HTTP
- **WHEN** o pipeline solicita áudio para um `TTSRequest`/SpeechChunk válido
- **THEN** a síntese ocorre localmente sem requisições de rede ao TTS e sem depender de `api_server` / URL `:8080`

#### Scenario: Worker isolado permitido
- **WHEN** o orquestrador executa a fase Fish Speech
- **THEN** a síntese MAY ocorrer em processo worker filho isolado controlado pelo LifecycleManager

### Requirement: Load e reuso do modelo dentro do worker
Os pesos MUST ser assegurados via ModelManager no máximo uma vez por necessidade de download/validação de cache por execução de geração. Dentro de uma única invocação do worker Fish, o engine GPU MUST ser reutilizado para a sequência de SpeechChunks dessa invocação sem reload completo entre chunks, enquanto o headroom permanecer seguro segundo o `VRAMGuardian`. O orquestrador MAY encerrar o worker e iniciar outro (reload em processo fresco) por fim de fase (sem pending), degradação de VRAM sinalizada pelo guardian, falha controlada, ou teto opcional de residency quando habilitado. MUST NÃO exigir novo download de pesos só porque um worker encerrou. MUST NÃO forçar reload mid-fase apenas por contagem fixa de chunks quando o teto opcional estiver desabilitado.

#### Scenario: Múltiplos chunks sem reload no mesmo worker
- **WHEN** vários SpeechChunks são sintetizados na mesma invocação do worker com headroom seguro
- **THEN** a síntese completa sem novo download e sem novo load completo de pesos/engine entre esses chunks

#### Scenario: Novo worker após exit por guardian
- **WHEN** um worker Fish encerra por sinal do guardian (progressive ou headroom) e o orquestrador inicia outro com cache de pesos íntegro
- **THEN** o novo worker carrega o engine a partir do cache local sem reiniciar download completo

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

### Requirement: Síntese orientada a SpeechChunks no worker
A fase TTS Fish Speech MUST consumir SpeechChunks limitados (não um livro/capítulo arbitrariamente grande numa única inferência). Cada chunk sintetizado MUST ser persistido antes do reclaim e registrado para resume.

#### Scenario: Chunk limitado sintetizado e persistido
- **WHEN** o worker recebe um SpeechChunk dentro dos limites configurados
- **THEN** produz áudio não vazio, persiste o artefato, e só então reclama memória temporária

### Requirement: Alocador PyTorch com expandable_segments no worker Fish
O processo worker Fish Speech MUST iniciar com configuração de alocador que habilite `expandable_segments` para reduzir OOM por fragmentação mid-fase (HIP/CUDA), salvo se o ambiente do usuário já definir explicitamente a variável correspondente. O orquestrador/spawn MUST preferir `PYTORCH_HIP_ALLOC_CONF` em stacks ROCm e MUST também assegurar `PYTORCH_CUDA_ALLOC_CONF` com `expandable_segments:True` quando apropriado e ainda não definido. Unexpected OOM MUST continuar sendo classificado e reportado; esta config MUST NÃO silenciar falhas.

#### Scenario: Worker recebe expandable_segments
- **WHEN** o orquestrador spawna o worker Fish e o usuário não overrideou as vars de alloc conf
- **THEN** o ambiente do processo filho inclui `expandable_segments:True` na(s) variável(is) de alloc conf aplicáveis

#### Scenario: Override do usuário preservado
- **WHEN** o usuário já exportou `PYTORCH_HIP_ALLOC_CONF` ou `PYTORCH_CUDA_ALLOC_CONF` antes do spawn
- **THEN** o valor do usuário é preservado (não sobrescrito às cegas pelo pipeline)

### Requirement: Pesos Fish seguem o alias selecionado
O backend Fish Speech in-process MUST carregar pesos obtidos via ModelManager para o alias `--fish-model` / default `s1-mini` (logical id correspondente). O contrato de síntese local sem HTTP e o isolamento em worker permanecem.

#### Scenario: Worker carrega path do alias ativo
- **WHEN** o worker Fish inicia com cache íntegro do alias selecionado (ex.: `s1-mini` ou `s2-pro`)
- **THEN** o engine é inicializado a partir do path desse alias sem baixar outro alias
