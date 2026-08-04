## ADDED Requirements

### Requirement: Pass A resume não re-emite chunks de capítulos já interpretados
Quando um capítulo é pulado por progresso de interpretação válido, o sistema MUST NÃO acrescentar novos SpeechChunks daquele capítulo ao manifest. Chunks já presentes MUST permanecer elegíveis às regras de resume TTS existentes (`pending`/`completed`/fingerprint).

#### Scenario: Skip de interpret preserva manifest do capítulo
- **WHEN** um capítulo está no progresso de interpretação e o generate é reexecutado
- **THEN** o número e identidade dos chunks daquele `chapter_id` no manifest permanecem inalterados por esse skip
