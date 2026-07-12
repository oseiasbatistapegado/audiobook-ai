## MODIFIED Requirements

### Requirement: Configuração de limites TTS
Os limites de SpeechChunk (e thresholds relacionados de VRAM usados na fase TTS) MUST ter defaults centralizados e MAY ser sobrescritos por configuração/CLI/env. O default de produto (alias Fish `s1-mini`) MUST ser **200** caracteres por SpeechChunk. Quando o alias ativo for `s2-pro` e o usuário NÃO tiver informado limite de chunk, o sistema MUST aplicar o preset **80** caracteres (estabilidade no footprint s2-pro). Override explícito CLI/env MUST ter precedência sobre o preset do alias.

#### Scenario: Default S1-mini sem override
- **WHEN** o usuário não informa limite de chunk TTS e o alias Fish é `s1-mini`
- **THEN** o pipeline usa 200 caracteres por SpeechChunk

#### Scenario: Preset s2-pro sem override
- **WHEN** `--fish-model s2-pro` está ativo e o usuário não informa limite de chunk
- **THEN** o pipeline usa 80 caracteres por SpeechChunk
