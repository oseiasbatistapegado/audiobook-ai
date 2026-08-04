## ADDED Requirements

### Requirement: Default de chunk TTS documentado como 5000
A CLI/documentação de `generate` MUST refletir o default de produto `TTS_MAX_CHUNK_CHARS=5000` e continuar permitindo override via flag/env existente. MUST NÃO apresentar a escada de calibração `500→4000` como passo obrigatório.

#### Scenario: Help/defaults mencionam 5000
- **WHEN** o usuário consulta help/docs do limite de chunk TTS
- **THEN** o default indicado é 5000 (salvo override)
