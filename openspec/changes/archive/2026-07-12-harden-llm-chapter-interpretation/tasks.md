## 1. Config e política de cache

- [x] 1.1 Adicionar em `config.py` defaults fechados: `LLM_INTERPRET_MAX_CHARS=6000`, `LLM_INTERPRET_MAX_ATTEMPTS=3`, `LLM_SPEAKER_QA_MIN_QUOTED_TURNS=6`, `LLM_SPEAKER_QA_DOMINANCE_THRESHOLD=0.85`, e `LLM_DIARIZATION_POLICY_VERSION`
- [x] 1.2 Estender `_adaptation_policy_id()` (ou equivalente) para incluir a política de diarização/QA/split e garantir cache miss vs entradas antigas

## 2. Prompt de diarização

- [x] 2.1 Atualizar `llm/prompts/interpret_chapter.md`: prosa/1ª pessoa → `narrator`; fala explícita do POV → protagonist id; um speaker por turno; sem misturar falantes; reuso de ids + `story_updates` para novos
- [x] 2.2 Cobrir em teste (ou assert de conteúdo) que o prompt carregado contém as regras de diarização (incl. narrador vs fala do POV)

## 3. Split e agregação de unidades

- [x] 3.1 Implementar módulo de split por parágrafo/sentença (`llm/units.py` ou similar) com limiar default 6000
- [x] 3.2 Implementar agregação ordenada de `dialogues` + merge determinístico de `story_updates`
- [x] 3.3 Integrar split → interpret sequencial com `story_state` acumulado → aggregate na API `interpret_chapter` (ou helper usado por ela)
- [x] 3.4 Cache por unidade (capítulo + índice/hash do trecho + política)
- [x] 3.5 Testes unitários: capítulo curto = 1 unidade; longo = N unidades; ordem de diálogos; merge de aliases; personagem da unidade 1 visível na 2

## 4. QA de diarização e retries

- [x] 4.1 Implementar checker com a regra AND: `quoted_turns >= 6` ∧ `dominant_speaker_ratio >= 0.85` ∧ `evidence_of_multiple_speakers >= 2` (story_state + atribuições locais)
- [x] 4.2 Refatorar loop de tentativas no `OllamaBackend` para cobrir JSON, Pydantic e QA até 3 tentativas, com mensagem de erro específica no retry
- [x] 4.3 Opcional mínimo: reparo mecânico de JSON (trailing commas) antes de falhar parse
- [x] 4.4 Garantir que falha de QA/schema/JSON NÃO grava cache de sucesso
- [x] 4.5 Testes: colapso rejeitado; monólogo aceito; terceira tentativa recupera; esgotamento aborta com contexto de unidade/capítulo

## 5. Regressão e docs

- [x] 5.1 Fixture obrigatória `ch-011` (Sudou/Ike/Yamauchi colapsados no protagonista): o checker MUST falhar nessa entrada
- [x] 5.2 Atualizar `docs/SMOKE.md` (ou equivalente) com nota de re-run: cache miss por política nova + como limpar manifesto/cache de runs com speakers ruins; documentar que `speaker_id=narrator` ≠ voz distinta obrigatória
- [x] 5.3 Rodar suite de testes afetada (`tests/test_*llm*`, sanitize, pipeline interpret mocks) e corrigir falhas
