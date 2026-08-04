## MODIFIED Requirements

### Requirement: Referência canônica pt-BR materializada
Após criar a identidade, o Voice Design MUST materializar áudio de referência falando português brasileiro natural, com texto alinhado (`reference.txt` ou `.lab`) correspondente ao conteúdo falado. Generic Portuguese / pt-PT inaceitável como resultado de sucesso. A referência MUST ser utilizável pelo ator TTS de produto (Qwen3-TTS Voice Clone).

#### Scenario: Metadata language pt-BR
- **WHEN** a geração conclui com sucesso
- **THEN** `GeneratedVoice.language` e metadata persistida declaram `pt-BR` e a passagem canônica está em português brasileiro

#### Scenario: Duração adequada para clonagem
- **WHEN** a referência é gerada para uso pelo ator TTS
- **THEN** o áudio respeita `VOICE_REF_MAX_SECONDS` (default **6.0** nesta change) e tem texto alinhado

### Requirement: Backend MVP Parler-TTS pt-BR com gate de spike
A implementação primária MUST ser o adapter Parler-TTS pt-BR pinado. O extra/dependências de Voice Design MUST ser autossuficientes: instalar suporte Parler + suporte Qwen3-TTS **sem** instalar `fish-speech` MUST permitir Voice Design funcional. A dependência de decode efetivamente usada pelo runtime Parler pinado MUST ser descoberta em ambiente sem Fish, declarada diretamente no extra `voice-parler`, e pinada; MUST NÃO permanecer como transitiva implícita via `fish-speech`. Após o spike, o projeto MUST registrar `DAC_PACKAGE` e `DAC_VERSION` confirmados.

#### Scenario: Parler sem fish-speech
- **WHEN** o ambiente tem extras Parler e Qwen3-TTS instalados e `fish-speech` ausente
- **THEN** o worker/gerador Parler consegue materializar `reference.wav` válido

#### Scenario: Gate composto de remoção do Fish
- **WHEN** `fish-speech` não está instalado, Parler gera `reference.wav`, e Qwen3-TTS clona essa referência com sucesso
- **THEN** o gate de remoção do Fish passa e a dependência DAC/decode está declarada no extra Parler

#### Scenario: Factory resolve gerador generativo
- **WHEN** a configuração default de voice generator está ativa
- **THEN** o factory retorna o gerador Parler, não um gerador Qwen VoiceDesign

### Requirement: Alternativa Qwen só após falha Parler
Qwen3-TTS VoiceDesign MUST NÃO ser adotado nesta change. Avaliação de Qwen como Voice Designer MUST ocorrer apenas em change separada (`evaluate-qwen3-tts-voice-design`) após a migração do ator estar estável. Portuguese genérico MUST NÃO ser tratado como prova de pt-BR.

#### Scenario: Voice Design Qwen fora de escopo
- **WHEN** esta change está implementada
- **THEN** o hot path de produto continua usando Parler para Voice Design e Qwen3-TTS Base apenas como ator Voice Clone
