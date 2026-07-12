## ADDED Requirements

### Requirement: voice_profile semântico opcional em story_updates
O contrato de interpretação MUST permitir que `story_updates.characters[]` incluam um objeto opcional `voice_profile` com hints semânticos para atribuição vocal (ex.: `gender`, `age_range`, `pitch`, `pace`, `energy`, `texture`, `personality`). A ausência de `voice_profile` MUST NÃO invalidar a resposta. O idioma canônico das vozes do produto permanece `pt-BR` e MUST NÃO depender de o LLM emitir um locale diferente para desviar o gerador.

#### Scenario: Personagem com voice_profile
- **WHEN** o JSON válido inclui um personagem novo com `voice_profile.gender` e demais hints reconhecidos
- **THEN** o modelo Pydantic aceita a resposta e o pipeline pode repassar o perfil ao `VoiceGenerator`

#### Scenario: Personagem sem voice_profile
- **WHEN** o JSON válido inclui um personagem sem campo `voice_profile`
- **THEN** a validação aceita o personagem e a atribuição de voz usa apenas `character_id` / defaults determinísticos

#### Scenario: Prompt documenta voice_profile
- **WHEN** o backend carrega o prompt de interpretação
- **THEN** o texto do prompt descreve o schema opcional de `voice_profile` e que a saída falável permanece em pt-BR
