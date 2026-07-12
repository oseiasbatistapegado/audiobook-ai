## ADDED Requirements

### Requirement: Feedback de handoff de VRAM na CLI
Quando o pipeline executar liberação de TTS, unload de LLM ou reload de TTS por handoff de VRAM, a CLI `generate` SHALL refletir essas etapas no progresso Rich (e logging), de forma que o usuário consiga distinguir handoff de falha silenciosa.

#### Scenario: Progresso durante handoff
- **WHEN** `audiobook-ai generate` processa um capítulo com Fish Speech + Ollama e ocorre transição entre interpret e TTS
- **THEN** o usuário vê indicação de progresso relacionada ao handoff (além das etapas `interpret` / `tts` existentes)
