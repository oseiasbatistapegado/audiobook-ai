## ADDED Requirements

### Requirement: Inferência Fish Speech in-process
O `FishSpeechBackend` MUST sintetizar áudio no mesmo processo Python do app, usando as APIs Python oficiais do Fish Speech (ex.: `TTSInferenceEngine` e loaders associados). MUST NÃO usar HTTP, FastAPI, chamadas a localhost, CLI do Fish Speech, ou `subprocess` para síntese.

#### Scenario: Síntese in-process
- **WHEN** o pipeline solicita áudio para um `TTSRequest` válido e o modelo já foi carregado
- **THEN** `FishSpeechBackend.synthesize` retorna um `AudioSegment` não vazio sem realizar requisições de rede ao TTS

#### Scenario: Proibição de servidor TTS
- **WHEN** o backend TTS Fish Speech está em uso
- **THEN** nenhuma dependência de `api_server`, URL `:8080`, ou health check HTTP é necessária para operar

### Requirement: Load único e reuso do modelo
O backend MUST carregar os pesos no máximo uma vez por instância/execução de geração e MUST reutilizar o modelo carregado para todos os segmentos/capítulos subsequentes. MUST NÃO recarregar pesos entre capítulos.

#### Scenario: Múltiplos segmentos sem reload
- **WHEN** vários `synthesize` são chamados na mesma instância do backend após o init
- **THEN** a síntese completa sem novo download e sem novo load completo de pesos entre as chamadas

### Requirement: Integração com ModelManager
Antes do primeiro load, o backend MUST obter o modelo via `ModelManager` (`ensure_model` / `get_model` para `fish-speech`). O restante do app (pipeline, CLI, state) MUST NÃO importar detalhes internos do Fish Speech além da interface `TTSBackend`.

#### Scenario: Primeira utilização baixa e carrega
- **WHEN** o modelo ainda não está em cache e o usuário inicia uma geração com backend `fish-speech`
- **THEN** o sistema assegura o modelo via manager, inicializa o engine uma vez e só então sintetiza

### Requirement: Sem cloud Fish Audio
O backend MUST NÃO chamar a API cloud Fish Audio (`api.fish.audio` ou equivalente). Toda inferência MUST ser local no processo.

#### Scenario: Sem credenciais cloud
- **WHEN** a síntese é executada
- **THEN** nenhuma API key de cloud TTS é exigida como caminho principal

## MODIFIED Requirements

### Requirement: Interface TTSBackend pluggable
O sistema SHALL expor uma interface `TTSBackend` com API única de síntese `synthesize(TTSRequest) -> AudioSegment`. Backends TTS MUST NÃO depender de implementações LLM ou extractors. Adicionar um novo backend no futuro MUST exigir apenas nova implementação + registro no factory (e id correspondente no `ModelManager` quando houver pesos).

#### Scenario: Factory resolve Fish Speech
- **WHEN** a configuração/pipeline solicita o backend `fish-speech`
- **THEN** o factory retorna uma instância de `FishSpeechBackend` que implementa `TTSBackend` e usa inferência in-process

### Requirement: Implementação Fish Speech como único backend TTS concreto
O change MUST implementar apenas Fish Speech como backend TTS concreto. Kokoro, Piper e XTTS MUST NÃO ser implementados neste change. A síntese SHALL usar texto, `voice_id` (do `voice_map`) e emotion do `TTSRequest`, retornando `AudioSegment` tipado.

#### Scenario: Síntese de um segmento
- **WHEN** o pipeline solicita áudio para um diálogo com texto, voice_id e emotion válidos e o modelo in-process está inicializado
- **THEN** `FishSpeechBackend` retorna um `AudioSegment` não vazio (opcionalmente persistindo WAV sob `out/chapters/`)

#### Scenario: Falha de load ou dispositivo
- **WHEN** o modelo não pode ser carregado (deps ausentes, GPU indisponível conforme política, pesos inválidos)
- **THEN** o sistema falha com erro contextual (backend, capítulo/segmento quando aplicável) sem cair para HTTP local

## REMOVED Requirements

### Requirement: Configuração do endpoint Fish Speech local
**Reason:** TTS deixa de ser cliente HTTP; não há servidor local a configurar.
**Migration:** Remover `--fish-speech-url` / `FISH_SPEECH_URL`; usar cache/`ModelManager` e backend in-process.

### Requirement: Implementação Fish-Audio S2 local no MVP
**Reason:** Substituído pelos requirements de inferência in-process e implementação concreta atualizados acima (o texto antigo exigia servidor self-hosted HTTP).
**Migration:** Usar `FishSpeechBackend` in-process + `ModelManager`; não subir `tools/api_server.py` para o app.
