## ADDED Requirements

### Requirement: Síntese com voz padrão empacotada
Além da interface in-process existente, o `FishSpeechBackend` MUST ser capaz de sintetizar áudio usando a voz padrão empacotada (`narrator`) sem que o usuário configure referências manualmente. A ausência de `./references/` do usuário MUST NÃO ser por si só um erro bloqueante quando os assets empacotados estão presentes.

#### Scenario: MVP smoke sem references manuais
- **WHEN** o pipeline solicita TTS com `voice_id` `narrator`, pesos carregados e assets `assets/voices/narrator/` presentes
- **THEN** `FishSpeechBackend.synthesize` retorna `AudioSegment` não vazio sem exigir setup manual de vozes pelo usuário

#### Scenario: voice_id desconhecido no smoke
- **WHEN** o `voice_map` referencia um `voice_id` sem pasta de referência e a voz `narrator` empacotada existe
- **THEN** o backend faz fallback para `narrator` (com log de aviso) em vez de falhar de forma opaca
