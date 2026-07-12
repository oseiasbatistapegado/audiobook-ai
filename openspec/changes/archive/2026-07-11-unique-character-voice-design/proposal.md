## Why

O MVP atual (`BankVoiceGenerator` + banco finito em `assets/voices/`) atribui ou reusa bases pré-existentes. Isso **não** cria identidade vocal sintética única por personagem e viola o requisito de produto: cada personagem relevante precisa de uma voz gerada automaticamente, condicionada ao `voice_profile`, em pt-BR, persistente e utilizável pelo Fish Speech. A change arquivada `auto-pt-br-character-voices` otimizou por pt-BR garantível via catálogo e precisa ser supersedida.

## What Changes

- Substituir a estratégia primária de banco fixo por **voice design generativo** (candidato MVP: Parler-TTS pt-BR `freds0/parler-tts-mini-v1.1-ptbr`; alternativa: Qwen3-TTS VoiceDesign se o spike Parler falhar).
- Introduzir/afirmar `ParlerVoiceGenerator` (e adapter futuro Qwen) atrás da abstração `VoiceGenerator`; o pipeline NÃO depende de APIs Parler/Qwen.
- Separar fases: Voice Design gera refs canônicas pt-BR **uma vez por personagem** → unload → Fish Speech sintetiza o audiobook.
- Escopar registry por audiobook: `voices/<book_id>/<character_id>/`.
- Seed determinístico via BLAKE2b/SHA-256 sobre `book_id + character_id + profile canônico + generator/version` (nunca `hash()`).
- **BREAKING**: `BankVoiceGenerator` deixa de ser o gerador padrão; reuse de `base_voice_id` / slots finitos deixa de ser política aceitável de sucesso.
- **BREAKING**: fallback silencioso para stock voice / voz de outro personagem / referência inglês é proibido.
- Spike técnico obrigatório (Carlos vs João, perfis similares, seeds distintos) antes de tratar Parler como production-ready; só então integrar no hot path.
- Narrator também recebe identidade dedicada pt-BR (perfil semântico de narração), nunca compartilhada com personagem.

## Capabilities

### New Capabilities

- `generative-voice-design`: geração de identidade vocal sintética única a partir de `CharacterProfile`/`VoiceProfile`, materialização de referência pt-BR alinhada, unload de modelo, e critérios de unicidade perceptiva (sem banco finito).

### Modified Capabilities

- `character-voice-generation`: remover requisitos de banco/catalog/reuse como solução primária; exigir gerador generativo e falha sem atribuição stock.
- `voice-registry`: paths scoped por `book_id`; metadata de generator/model/seed/profile; persistido vence regeneração.
- `default-voice`: narrator passa a ser voz dedicada gerada (ou configurada) pt-BR, não apenas asset empacotado de banco.
- `tts-fish-speech`: Fish Speech só clona refs persistidas; NÃO cria identidade; MUST preservar distinção entre speakers nas refs geradas.
- `story-state`: atribuição de voz ligada a geração única scoped ao livro; `voice_map` aponta para identidades com refs reais geradas.
- `llm-interpretation`: manter `voice_profile` semântico; reforçar que o LLM NÃO emite parâmetros de backend; locale canônico pt-BR.

## Impact

- Código: `voice/generator.py`, registry, `ensure_voice`, pipeline (fase batch de vozes faltantes + VRAM handoff), config (`VOICE_GENERATOR_DEFAULT`), possivelmente ModelManager para pesos Parler.
- Dependências: novo extra/grupo para Parler-TTS pt-BR (e spike Qwen sob demanda); ROCm / RX 7900 XTX.
- Specs main sincronizadas da change de banco passam a ser deltas de correção nesta change.
- Docs/SMOKE: smoke deixa de depender de slots em `assets/voices/` como solução; exige 3 vozes geradas distintas + Fish Speech preservando identidade.
- Assets Piper/Kokoro empacotados deixam de ser arquitetura primária (podem permanecer só como ferramenta de teste, não como fallback de produto).
