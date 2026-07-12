## Why

Hoje o pipeline atribui IDs simbólicos (`narrator`, `voice_01`…) sem assets reais para a maioria deles, e a única voz empacotada (`narrator`) é um clipe de smoke em inglês — o Fish Speech clona sotaque da referência, então o áudio em texto pt-BR soa incorreto (frequentemente “não-brasileiro”). O usuário não deve ter de fornecer referência manual por personagem; o sistema precisa criar/atribuir identidades vocais persistentes e **pt-BR** automaticamente.

## What Changes

- Introduzir geração/atribuição automática de vozes por personagem com metadados `language=pt-BR` explícitos.
- Introduzir abstração `VoiceGenerator` (independente do Fish Speech) que produz referências reutilizáveis (`reference.wav` + texto alinhado + metadata).
- Popular e gerenciar um **banco curado de vozes base pt-BR** + atribuição determinística a partir de perfil vocal semântico do LLM (MVP); Fish Speech continua como único sintetizador do livro.
- Persistir vozes em cache (`~/.cache/audiobook-ai/voices/` ou equivalente) e mapear `character_id → voice_id` estável em `story.json`.
- Substituir/atualizar a voz default `narrator` para uma referência **pt-BR** dedicada (não compartilhada com personagens).
- Estender o contrato do LLM director com `voice_profile` opcional ao introduzir personagens.
- Remover o comportamento de round-robin sobre IDs fantasmas (`voice_01`…`voice_05` sem pastas reais) como caminho principal.
- Falhas de geração NÃO atribuem voz aleatória silenciosa; fallback documentado só para vozes pt-BR conhecidas.

## Capabilities

### New Capabilities
- `character-voice-generation`: Geração/atribuição automática de identidade vocal pt-BR por personagem (perfil semântico → voz persistente → referência utilizável pelo TTS).
- `voice-registry`: Registro e cache em disco de vozes geradas/atribuídas (`metadata.json`, `reference.wav`, texto de referência) com seed determinístico e `language=pt-BR`.

### Modified Capabilities
- `story-state`: `voice_map` passa a apontar para vozes com assets reais no registry; atribuição deixa de ser round-robin sobre IDs sem referência.
- `default-voice`: Narrator default MUST ser pt-BR; política de resolução inclui registry/cache além de assets empacotados.
- `tts-fish-speech`: Resolução de `voice_id` consulta registry/cache pt-BR; fallback para voz não-pt-BR conhecida é proibido; fallback opaco para `narrator` inglês deixa de ser aceitável.
- `llm-interpretation`: Prompt/schema aceitam `voice_profile` semântico opcional em `story_updates.characters` (hints para o VoiceGenerator).

## Impact

- Código: `state/voices.py`, `models/character.py` / novos modelos de perfil, `pipeline.py`, `tts/voices.py`, `config.py`, prompt `interpret_chapter.md`, novos módulos `voice/` (generator + registry).
- Assets: banco inicial de referências pt-BR (licença OK) sob `assets/voices/` e/ou materialização no cache.
- Deps: MVP sem novo motor TTS no hot path; possível uso one-shot de Piper/Kokoro só para *seed* offline do banco (documentado no design). Sem cloud TTS.
- Runtime: Fish Speech permanece único sintetizador; VRAM handoff LLM↔TTS inalterado no hot path.
- Testes: unitários de atribuição/persistência/determinismo + smoke auditivo pt-BR com ≥3 vozes distintas.
