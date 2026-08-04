## Purpose

Partição determinística do texto interpretado em `SpeechChunk`s limitados, com persistência imediata do áudio por chunk.

## Requirements

### Requirement: SpeechChunk como unidade TTS limitada
O pipeline SHALL dividir o trabalho de síntese em `SpeechChunk`s com identificador estável, sequência determinística, texto limitado e metadata suficiente para resume (incluindo vínculo a capítulo/personagem/emotion quando aplicável). Um SpeechChunk MUST NÃO conter texto arbitrariamente grande; limites MUST ser configuráveis (ex.: máximo de caracteres).

#### Scenario: Chunk IDs determinísticos
- **WHEN** o mesmo input interpretado e a mesma configuração de chunking são aplicados duas vezes
- **THEN** a sequência de SpeechChunk ids e ordem é idêntica

#### Scenario: Limite de tamanho respeitado
- **WHEN** um diálogo ou narração excede o máximo configurado
- **THEN** o texto é particionado em múltiplos SpeechChunks dentro do limite (usando boundaries preferenciais)

### Requirement: Boundaries preferenciais de speech chunking
A partição de SpeechChunks SHOULD preferir, nesta ordem: parágrafo, turno de diálogo, sentença, e só então split por limite de caracteres como último recurso. LLM semantic chunking MUST NÃO ser requisito deste capability.

#### Scenario: Turno de diálogo cabe em um chunk
- **WHEN** um turno de diálogo está abaixo do limite configurado
- **THEN** o turno permanece em um único SpeechChunk sem split desnecessário

### Requirement: Persistência imediata do áudio do chunk
Após sintetizar um SpeechChunk com sucesso, o sistema MUST persistir o áudio do chunk em disco antes de reclaim de memória no worker e antes de iniciar o próximo chunk.

#### Scenario: WAV existe antes do próximo chunk
- **WHEN** o chunk N é sintetizado com sucesso
- **THEN** o arquivo de áudio correspondente está persistido antes do reclaim e antes da síntese do chunk N+1

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
