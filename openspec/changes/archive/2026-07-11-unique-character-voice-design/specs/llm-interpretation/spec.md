## MODIFIED Requirements

### Requirement: voice_profile semântico opcional em story_updates
O contrato de interpretação MUST permitir que `story_updates.characters[]` incluam um objeto opcional `voice_profile` com hints semânticos para voice design (ex.: `gender`, `age_range`, `pitch`, `pace`, `energy`, `texture`, `personality`). A ausência de `voice_profile` MUST NÃO invalidar a resposta. O idioma canônico das vozes permanece `pt-BR`. O LLM MUST NÃO emitir parâmetros específicos de backend (Parler/Qwen/etc.); o adapter do `VoiceGenerator` traduz o perfil estruturado.

#### Scenario: Personagem com voice_profile
- **WHEN** o JSON válido inclui um personagem novo com `voice_profile.gender` e demais hints reconhecidos
- **THEN** o modelo Pydantic aceita a resposta e o pipeline pode repassar o perfil ao `VoiceGenerator` generativo

#### Scenario: Personagem sem voice_profile
- **WHEN** o JSON válido inclui um personagem sem campo `voice_profile`
- **THEN** a validação aceita o personagem e a geração usa defaults determinísticos + `character_id`/`book_id`

#### Scenario: Prompt documenta voice_profile sem APIs de backend
- **WHEN** o backend carrega o prompt de interpretação
- **THEN** o texto descreve o schema opcional de `voice_profile`, saída falável em pt-BR, e NÃO instrui o modelo a emitir parâmetros Parler/Qwen
