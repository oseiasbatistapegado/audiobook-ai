## ADDED Requirements

### Requirement: Mudança de TTS_MAX_CHUNK_CHARS invalida fingerprint de resume
Alterar `TTS_MAX_CHUNK_CHARS` (ou equivalente usado em `chunking_fingerprint`) MUST alterar o fingerprint de chunking. Manifests da fase TTS gravados com fingerprint incompatível MUST NÃO ser reutilizados cegamente: a fase TTS desses artefatos MUST ser regenerada (ou falhar de forma explícita conforme a política de resume já existente).

#### Scenario: Aumentar chunk size força regeneração TTS
- **WHEN** um work-dir possui manifest completed sob fingerprint de `TTS_MAX_CHUNK_CHARS=200` e a execução atual usa `500`
- **THEN** o sistema não reutiliza cegamente os áudios incompatíveis e trata a fase TTS como inválida para resume cego

#### Scenario: Mesmo fingerprint permite resume
- **WHEN** o fingerprint de chunking no manifest coincide com a execução atual
- **THEN** chunks `completed` válidos continuam elegíveis a skip/resume
