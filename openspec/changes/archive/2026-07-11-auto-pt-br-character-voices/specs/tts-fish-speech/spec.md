## MODIFIED Requirements

### Requirement: Síntese com voz padrão empacotada
Além da interface in-process existente, o `FishSpeechBackend` MUST ser capaz de sintetizar áudio usando a voz padrão empacotada/registrada (`narrator` pt-BR) sem que o usuário configure referências manualmente. A ausência de `./references/` do usuário MUST NÃO ser por si só um erro bloqueante quando os assets empacotados ou o registry pt-BR estão presentes. A resolução de `voice_id` MUST consultar a precedência documentada (override usuário → registry/cache → assets) e MUST NÃO usar como fallback silencioso uma voz de idioma diferente de `pt-BR`.

#### Scenario: MVP smoke sem references manuais
- **WHEN** o pipeline solicita TTS com `voice_id` `narrator`, pesos carregados e assets/registry `narrator` pt-BR presentes
- **THEN** `FishSpeechBackend.synthesize` retorna `AudioSegment` não vazio sem exigir setup manual de vozes pelo usuário

#### Scenario: voice_id com registry pt-BR
- **WHEN** o `voice_map` referencia um `voice_id` materializado no registry com `language=pt-BR`
- **THEN** o backend sintetiza usando essa referência (não substitui por narrator sem necessidade)

#### Scenario: voice_id sem referência pt-BR válida
- **WHEN** o `voice_map` referencia um `voice_id` sem pasta resolvível pt-BR e não há fallback pt-BR documentado aplicável
- **THEN** o backend falha com erro contextual (em vez de clonar silenciosamente uma referência de outro idioma)

## ADDED Requirements

### Requirement: Consumo de vozes do registry sem regenerar por frase
O backend TTS MUST tratar `voice_id` como identidade já materializada: MUST NÃO regenerar a referência vocal a cada `synthesize`. A geração/atribuição de voz ocorre uma vez por personagem via `VoiceGenerator`/registry; a síntese ocorre muitas vezes.

#### Scenario: Múltiplos synthesize reutilizam a mesma ref
- **WHEN** vários `synthesize` são chamados com o mesmo `voice_id` válido na mesma geração
- **THEN** cada chamada usa a mesma pasta de referência já resolvida sem invocar `VoiceGenerator.generate_voice` novamente
