## 1. Progresso de interpretação

- [x] 1.1 Criar modelo + load/save atômico de `interpret_progress.json` sob `BookWorkLayout` (chapter ids, model, policy versions)
- [x] 1.2 Implementar bootstrap legado: marcar chapter_ids do manifest exceto o último na ordem do livro
- [x] 1.3 Invalidar progresso quando model/políticas da execução atual diferirem dos gravados
- [x] 1.4 Testes unitários de load/save, bootstrap e invalidação

## 2. Cache LLM estável

- [x] 2.1 Extrair fingerprint estável de elenco (ids + aliases ordenados) a partir de `StoryState`
- [x] 2.2 Alterar `_cache_key` para usar fingerprint + unit/model/policies — não o dump completo de `story_state`
- [x] 2.3 Bump de `LLM_DIARIZATION_POLICY_VERSION` (ou fragmento equivalente) para invalidar caches com chave antiga
- [x] 2.4 Testes: hit com voice_map diferente / mesmo elenco; miss com novo character_id; miss com policy nova

## 3. Pipeline Pass A — skip e unload

- [x] 3.1 No loop Pass A, pular capítulos em progresso válido (log + progress `interpret-skip`); não chamar interpret/merge/voice-design
- [x] 3.2 Após sucesso de interpret (+ story + manifest), append `chapter_id` e persistir progresso
- [x] 3.3 Unload Ollama apenas antes de Voice Design com trabalho GPU, ou antes do Pass B TTS — não após todo capítulo
- [x] 3.4 Garantir unload + wait antes do Voice Design e antes de `run_tts_phase`
- [x] 3.5 Testes de pipeline: restart pula capítulos marcados; manifest inalterado no skip; unload não chamado entre caps sem VD

## 4. Integração e docs

- [x] 4.1 Atualizar `docs/SMOKE.md` (ou nota curta) com restart mid-interpret e expectativa de skip
- [x] 4.2 Rodar suite relevante (`test_llm`, pipeline/vram handoff, novos testes de resume)
