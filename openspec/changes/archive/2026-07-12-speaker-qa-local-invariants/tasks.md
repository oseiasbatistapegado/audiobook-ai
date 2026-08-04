## 1. Invariantes no checker

- [x] 1.1 Estender `llm/speaker_qa.py` com invariante de narração (turno sem fala explícita → MUST `narrator`)
- [x] 1.2 Adicionar invariante de atribuição explícita (padrões no `dialogues[].text` resolvidos via `story_state`)
- [x] 1.3 Manter dominance intacta; prefixar erros (`narration` / `attribution` / `dominance`); NÃO avaliar PT-BR neste gate
- [x] 1.4 Bump `LLM_DIARIZATION_POLICY_VERSION` para `v2`

## 2. Regressão e testes

- [x] 2.1 Fixture obrigatória `ch-004` (prosa→POV + fala Horikita no Ayanokoji) que falha com dominance < 0.85
- [x] 2.2 Garantir que `ch-011` ainda falha; monólogo/narrator-only e atribuição alinhada passam
- [x] 2.3 Teste: calque PT-BR com speakers corretos NÃO falha o gate de diarização
- [x] 2.4 Rodar `tests/test_speaker_qa.py` + `tests/test_llm.py` e corrigir falhas

## 3. Run Classroom / docs

- [x] 3.1 Documentar em `docs/SMOKE.md`: interromper antes do TTS se manifesto tiver speakers ruins; limpar manifesto + cache LLM (`diarization v2`) antes de re-interpretar
- [x] 3.2 Nota operacional: work-dir `out/classroom/...` atual tem chunks pending sem áudio — apagar manifesto/cache antes da próxima generate após este change
