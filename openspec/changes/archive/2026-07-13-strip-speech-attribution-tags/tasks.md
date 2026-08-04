## 1. Prompt e política de cache

- [x] 1.1 Atualizar `interpret_chapter.md` para proibir speech-tags de atribuição no `text` de falas de personagem (só palavras faladas; atribuição informa `speaker_id`)
- [x] 1.2 Bump `LLM_DIARIZATION_POLICY_VERSION` de `v5` para `v6`

## 2. Repair determinístico

- [x] 2.1 Implementar `strip_speech_attribution_tags` (ou equivalente) que remove tags `disse/perguntou/… + ela/ele/nome` de turnos não-narrator e deixa narrador intacto
- [x] 2.2 Integrar no `OllamaBackend` na ordem: sanitize → Pydantic → `repair_narration_speakers` → strip → `check_speaker_diarization`
- [x] 2.3 Tratar texto vazio pós-strip como falha de interpretação (não sucesso)

## 3. QA de speech-tag

- [x] 3.1 Adicionar invariante `speaker QA speech-tag` para turnos de personagem com tag residual (incluindo pronomes)
- [x] 3.2 Garantir que prosa de narrador com “disse que” NÃO falha só por esse motivo

## 4. Testes e fixtures

- [x] 4.1 Fixture de regressão `ch-004` speech-tag (`disse ela` / `perguntou ela`) + testes de strip e QA
- [x] 4.2 Teste de não-regressão: narrador com “pensador disse que…” permanece intacto
- [x] 4.3 Cobrir cache/policy bump (`v6`) nos testes existentes de chave de cache, se aplicável
