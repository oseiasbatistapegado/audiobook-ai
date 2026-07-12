## ADDED Requirements

### Requirement: Override opcional do teto de residency Fish
A CLI e/ou env MUST permitir override do teto opcional de chunks por invocação do worker Fish (`--fish-chunks-per-worker` e/ou `AUDIOBOOK_AI_FISH_CHUNKS_PER_WORKER`, ou equivalente documentado). Default MUST ser desabilitado (guardian-driven). Valor >0 reativa EXIT por contagem como escape hatch. A CLI MUST NÃO apresentar o teto como política primária de segurança de VRAM.

#### Scenario: Default guardian-driven sem teto
- **WHEN** o usuário executa `generate` sem override de teto de residency
- **THEN** o worker Fish não reinicia só por contagem fixa de chunks

#### Scenario: Escape hatch via flag/env
- **WHEN** o usuário define teto >0 via flag ou env suportada
- **THEN** o worker pode emitir restart com `restart_reason=residency` ao atingir esse teto
