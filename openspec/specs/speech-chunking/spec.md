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
Os limites de SpeechChunk (e thresholds relacionados de VRAM usados na fase TTS) MUST ter defaults centralizados e MAY ser sobrescritos por configuração/CLI/env. O default de produto (alias Fish `s1-mini`) MUST ser **200** caracteres por SpeechChunk. Quando o alias ativo for `s2-pro` e o usuário NÃO tiver informado limite de chunk, o sistema MUST aplicar o preset **80** caracteres (estabilidade no footprint s2-pro). Override explícito CLI/env MUST ter precedência sobre o preset do alias.

#### Scenario: Default S1-mini sem override
- **WHEN** o usuário não informa limite de chunk TTS e o alias Fish é `s1-mini`
- **THEN** o pipeline usa 200 caracteres por SpeechChunk

#### Scenario: Preset s2-pro sem override
- **WHEN** `--fish-model s2-pro` está ativo e o usuário não informa limite de chunk
- **THEN** o pipeline usa 80 caracteres por SpeechChunk
