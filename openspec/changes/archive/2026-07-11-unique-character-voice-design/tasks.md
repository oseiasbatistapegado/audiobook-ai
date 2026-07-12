## 1. Spike Parler-TTS pt-BR (gate)

- [x] 1.1 Adicionar deps/script isolado para `freds0/parler-tts-mini-v1.1-ptbr` (extra opcional; não acoplar ao hot path ainda)
- [x] 1.2 Definir passagem canônica pt-BR (alvo ~15s, faixa 10–30s) e dois perfis similares (Carlos / João) com seeds distintos
- [ ] 1.3 Gerar duas refs WAV + texto alinhado; validar pt-BR auditivo (borderline = FAIL) e unicidade perceptiva
- [ ] 1.4 Passar ambas as refs pelo Fish Speech com a mesma frase; validar que a distinção de speaker se preserva
- [x] 1.5 Medir VRAM load/unload do Parler sob ROCm (7900 XTX) e registrar números no `design.md`
- [ ] 1.6 Registrar veredito go/no-go Parler no `design.md` (Open Questions); se no-go, NÃO implementar banco como substituto

## 2. Spike Qwen (somente se Parler falhar)

- [ ] 2.1 Executar protocolo equivalente com Qwen3-TTS VoiceDesign
- [ ] 2.2 Validar especialmente sotaque pt-BR vs pt-PT + preservação no Fish Speech
- [ ] 2.3 Escolher default de produção e documentar no design

## 3. Modelos e registry book-scoped

- [x] 3.1 Estender `GeneratedVoice` / metadata com `character_id`, `model_id`, `generator_version`, snapshot de `voice_profile`
- [x] 3.2 Definir `book_id` = BLAKE2b-128 do conteúdo do input (rename/move não altera) e atualizar `VoiceRegistry` para `voices/<book_id>/<character_id>/`
- [x] 3.3 Atualizar seed BLAKE2b para incluir `book_id` + model/version; manter “persistido vence”
- [x] 3.4 Garantir falha sem stock/share/inglês/`voice_id` simbólico

## 4. VoiceGenerator generativo

- [x] 4.1 Implementar adapter `ParlerVoiceGenerator` (ou Qwen escolhido) traduzindo `VoiceProfile` → condicionamento backend
- [x] 4.2 Factory: default deixa de ser `bank`; `BankVoiceGenerator` fora do caminho de sucesso do produto
- [x] 4.3 Perfil narrator = `VoiceProfile` constante MVP (mesmo domínio; arquitetura permite config futura)

- [x] 4.4 API de unload/release do modelo de Voice Design

## 5. Pipeline e VRAM

- [x] 5.1 Fase batch: descobrir vozes faltantes do `book_id` → gerar todas → persistir → unload Voice Design → load Fish Speech
- [x] 5.2 Remover geração por segmento / dependência de slots de banco em `ensure_voice`
- [x] 5.3 Resolução TTS: override usuário → registry do livro → falha explícita (sem fallback bank/en)

## 6. Testes, docs e aceite

- [x] 6.1 Testes unitários: seed estável, registry book-scoped, persistido vence, falha sem poluir `voice_map`
- [x] 6.2 Atualizar README/SMOKE: sem banco finito como solução; critério de 3 vozes geradas + restart
- [ ] 6.3 Smoke E2E: Narrator + ≥2 personagens; 3 identidades distintas; pt-BR; Fish Speech preserva distinção; M4B
- [x] 6.4 Remover/ajustar testes que exigem reuse de banco ou `BankVoiceGenerator` como default
