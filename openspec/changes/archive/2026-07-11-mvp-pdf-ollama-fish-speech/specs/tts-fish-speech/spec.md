## ADDED Requirements

### Requirement: Interface TTSBackend pluggable
O sistema SHALL expor uma interface `TTSBackend` com API única de síntese (ex.: `synthesize(TTSRequest) -> AudioSegment`). Backends TTS MUST NÃO depender de implementações LLM ou extractors. Adicionar um novo backend no futuro MUST exigir apenas nova implementação + registro no factory.

#### Scenario: Factory resolve Fish Speech
- **WHEN** a configuração/pipeline solicita o backend `fish-speech`
- **THEN** o factory retorna uma instância de `FishSpeechBackend` que implementa `TTSBackend`

### Requirement: Implementação Fish-Audio S2 local no MVP
O MVP MUST implementar apenas Fish Speech (Fish-Audio S2) como backend TTS concreto, falando com um **servidor self-hosted local**. O backend SHALL gerar áudio a partir de texto, voice id (do `voice_map`, tipicamente `reference_id` local) e emotion padronizada, retornando `AudioSegment` tipado. Kokoro, Piper e XTTS MUST NÃO ser implementados neste change. O backend MUST NÃO chamar a API cloud Fish Audio.

#### Scenario: Síntese de um segmento via API local
- **WHEN** o pipeline solicita áudio para um diálogo com texto, voice_id e emotion válidos e o servidor local responde em `POST /v1/tts`
- **THEN** `FishSpeechBackend` retorna um `AudioSegment` não vazio (ou persiste arquivo de áudio sob `out/` referenciado pelo modelo)

#### Scenario: Servidor Fish Speech indisponível
- **WHEN** o endpoint configurado de Fish Speech não responde (ex.: health check `GET /v1/health` falha)
- **THEN** o sistema falha com erro contextual incluindo URL/backend e capítulo/segmento em processamento

#### Scenario: Proibição de cloud TTS
- **WHEN** a configuração aponta para um host que não seja o servidor local self-hosted do usuário
- **THEN** o design e defaults MUST permanecer centrados em `http://127.0.0.1:8080` (ou URL local equivalente); não há integração cloud neste change

### Requirement: Configuração do endpoint Fish Speech local
A URL do serviço Fish Speech MUST ser configurável (CLI e/ou variável de ambiente / `config.py`), com default local `http://127.0.0.1:8080` alinhado a `tools/api_server.py --listen …:8080`. Endpoints esperados do servidor local: `GET /v1/health`, `POST /v1/tts` (e opcionalmente VQ encode/decode). O processo do servidor (clone fish-speech, pesos `s2-pro`, Docker ROCm ou install nativo) MUST permanecer externo ao pacote `audiobook_ai`.

#### Scenario: Override de URL
- **WHEN** o usuário passa `--fish-speech-url` (ou equivalente)
- **THEN** o backend usa essa URL em vez do default local

#### Scenario: Health check antes ou na falha de síntese
- **WHEN** a síntese falha por conexão ou o pipeline verifica disponibilidade
- **THEN** a mensagem de erro MUST mencionar a URL configurada e orientar a subir o API server local (não a conta cloud)
