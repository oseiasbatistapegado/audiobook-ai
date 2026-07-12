## 1. Models e contrato LLM

- [x] 1.1 Adicionar modelos Pydantic `VoiceProfile`, `CharacterProfile` / extensão de `Character`, e `GeneratedVoice` (voice_id, language, paths, generator, seed)
- [x] 1.2 Estender `StoryUpdates` / schema de personagem para aceitar `voice_profile` opcional sem quebrar respostas existentes
- [x] 1.3 Atualizar `interpret_chapter.md` com schema e regras de `voice_profile` (hints semânticos; locale canônico pt-BR)
- [x] 1.4 Ajustar testes de prompt/LLM para cobrir presença do schema opcional e validação com/sem `voice_profile`

## 2. Voice registry e resolução de paths

- [x] 2.1 Implementar `VoiceRegistry` com persistência em `<cache-root>/voices/<voice_id>/` (`metadata.json`, `reference.wav`, `reference.lab`/`reference.txt`)
- [x] 2.2 Implementar ensure/get idempotente e rejeição de `language != pt-BR` no fluxo automático
- [x] 2.3 Atualizar resolução de voz (`tts/voices.py` ou módulo compartilhado) com precedência: user `references/` → registry → `assets/voices/`
- [x] 2.4 Remover/ajustar fallback silencioso para referência não-pt-BR; falha contextual quando não houver voz pt-BR válida

## 3. VoiceGenerator (banco pt-BR)

- [x] 3.1 Definir interface/protocol `VoiceGenerator` e factory do gerador MVP (`BankVoiceGenerator`)
- [x] 3.2 Implementar catálogo de vozes base descobertos dinamicamente (metadata: language, gender/tags, license) sem hardcode de capacidade; seleção determinística via BLAKE2b/SHA-256 (não `hash()`)
- [x] 3.3 Preferir bases compatíveis unused; após esgotamento, reuse determinístico (narrator excluído do pool de personagens)
- [x] 3.4 Materializar voz por `character_id` no registry (cópia da base + metadata com seed, base_voice_id, language=pt-BR, proveniência); persistido sempre vence re-seleção
- [x] 3.5 Reservar slot do narrator: voz dedicada pt-BR fora do pool de personagens
- [x] 3.6 Tratar falha de geração sem gravar `voice_map` aleatório; permitir retry; fallback opcional só para narrator pt-BR com warning

## 4. Assets pt-BR

- [x] 4.1 Substituir `assets/voices/narrator/` por referência pt-BR (wav + lab/texto + metadata `language=pt-BR`)
- [x] 4.2 Empacotar 5 vozes base de personagem distintas pt-BR (tags de gênero/idade) com licença documentada — total MVP = 6 com narrator
- [x] 4.3 Adicionar script offline opcional de seed/reprodutibilidade via Piper `pt_BR` e/ou Kokoro BR (nunca no hot path); assets pré-gerados validados são o default shipado
- [ ] 4.4 Smoke auditivo humano obrigatório: confirmar sotaque BR nas refs empacotadas (sem validador automático de accent no MVP)

## 5. Integração no pipeline / story-state

- [x] 5.1 Substituir `ensure_voice` round-robin de IDs fantasmas por fluxo generator + registry + `voice_map` estável
- [x] 5.2 Integrar no `pipeline.py`: após `story_updates`, garantir voz na primeira aparição; reutilizar nas seguintes
- [x] 5.3 Garantir que Fish Speech apenas consome refs já materializadas (sem regenerate por frase)
- [x] 5.4 Atualizar `config.py` (remover dependência de `voice_01`… sem assets; defaults alinhados ao banco/narrator)
- [x] 5.5 Atualizar README/SMOKE com fluxo de vozes automáticas pt-BR e override `./references/`

## 6. Testes e smoke

- [x] 6.1 Testes: novo personagem recebe voz; personagem existente reutiliza; narrator dedicado
- [x] 6.2 Testes: metadata `language=pt-BR` + `base_voice_id`; cache sobrevive restart; seeds/IDs determinísticos estáveis; persistido vence re-seleção
- [x] 6.3 Testes: falha de geração não atribui voz aleatória silenciosa; rejeita language inválida; reuse determinístico após esgotamento do pool
- [ ] 6.4 Smoke real: PDF curto PT com Narrator + Carlos + Maria; 3 vozes distintas; pronúncia pt-BR inteligível; M4B gerado
- [x] 6.5 Ajustar testes existentes de fallback/default-voice quebrados pela nova política pt-BR
