## MODIFIED Requirements

### Requirement: Configuração de limites TTS
Os limites de SpeechChunk (e thresholds relacionados de VRAM usados na fase TTS) MUST ter defaults centralizados e MAY ser sobrescritos por configuração/CLI/env. O default de produto MUST ser **5000** caracteres por SpeechChunk (`TTS_MAX_CHUNK_CHARS`). Presets Fish e a escada de calibração `500 → 1000 → 2000 → 4000` MUST NÃO permanecer como política de produto. Override explícito CLI/env MUST ter precedência. Aumentar o limite MUST NÃO concatenar turnos de personagens/speakers diferentes; cada unidade de diálogo permanece um SpeechChunk preferencial, e só é particionada quando ultrapassa o limite (fronteiras naturais: parágrafo, sentença, depois chars).

#### Scenario: Default 5000 sem override
- **WHEN** o usuário não informa limite de chunk TTS
- **THEN** o pipeline usa 5000 caracteres por SpeechChunk

#### Scenario: Override via CLI/env
- **WHEN** o usuário informa um limite de chunk via flag ou env suportada
- **THEN** o pipeline usa esse valor em vez do default

#### Scenario: Sem misturar speakers ao aumentar o limite
- **WHEN** dois turnos consecutivos têm speakers distintos e cada um cabe no limite
- **THEN** permanecem SpeechChunks separados (não concatenados artificialmente)

#### Scenario: Turno acima de 5000 é particionado
- **WHEN** um único turno excede 5000 caracteres
- **THEN** o sistema particiona esse turno em múltiplos SpeechChunks nas fronteiras preferenciais sem misturar outros speakers
