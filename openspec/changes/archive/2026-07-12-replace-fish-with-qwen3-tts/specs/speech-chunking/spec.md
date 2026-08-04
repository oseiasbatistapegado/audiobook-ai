## MODIFIED Requirements

### Requirement: Configuração de limites TTS
Os limites de SpeechChunk (e thresholds relacionados de VRAM usados na fase TTS) MUST ter defaults centralizados e MAY ser sobrescritos por configuração/CLI/env. O default inicial de produto MUST ser **500** caracteres por SpeechChunk (`TTS_MAX_CHUNK_CHARS`). Presets Fish `s1-mini` (200) e `s2-pro` (80) MUST NÃO permanecer como defaults de produto. A calibração obrigatória MUST avaliar sequencialmente 500, 1000, 2000 e 4000 no hardware oficial com as mesmas refs/textos/ambiente; o default final MUST ser o maior tamanho aprovado sem regressão perceptível de qualidade, prosódia ou estabilidade (não o maior que apenas cabe na VRAM). Override explícito CLI/env MUST ter precedência. Aumentar o limite MUST NÃO concatenar turnos de personagens diferentes (o particionamento por diálogo/speaker permanece).

#### Scenario: Default 500 sem override
- **WHEN** o usuário não informa limite de chunk TTS
- **THEN** o pipeline usa 500 caracteres por SpeechChunk

#### Scenario: Calibração não promove automaticamente o maior valor
- **WHEN** 4000 cabe na VRAM mas degrada prosódia/qualidade vs 2000 aprovado
- **THEN** o default final documentado MUST NÃO ser 4000

#### Scenario: Override via CLI/env
- **WHEN** o usuário informa um limite de chunk via flag ou env suportada
- **THEN** o pipeline usa esse valor em vez do default

#### Scenario: Sem misturar speakers ao aumentar o limite
- **WHEN** dois turnos consecutivos têm speakers distintos e cada um cabe no limite
- **THEN** permanecem SpeechChunks separados (não concatenados artificialmente)
