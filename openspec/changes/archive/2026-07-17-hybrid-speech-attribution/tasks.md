## 1. Modelos e dados

- [x] 1.1 Adicionar `UnitClassification` dataclass em `models/cast.py`
  - Campos: `unit_index: int`, `classification: str` ("narration"|"explicit_dialogue"|"indirect_dialogue"|"ambiguous"), `is_indirect: bool`
- [x] 1.2 Adicionar `TurnAttribution` dataclass em `models/cast.py`
  - Campos: `unit_index: int`, `speaker_id: str`, `confidence: float`, `evidence: list[EvidenceEntry]`
- [x] 1.3 Adicionar `EvidenceType.FIRST_PERSON` em `models/cast.py`
- [x] 1.4 Adicionar `EvidenceType.TURN_TRACKER` em `models/cast.py`

## 2. Unit Classifier (determinístico, 4 classes)

- [x] 2.1 Criar `llm/unit_classifier.py` com classe `UnitClassifier`
- [x] 2.2 Implementar `classify_unit(unit_text: str) -> UnitClassification`
  - Padrão 1: aspas (`"`, `""`, `«», `»`, `「`, `」`, `『`, `』`) → `explicit_dialogue`
  - Padrão 2: travessão (`—`, `–`) no início → `explicit_dialogue`
  - Padrão 3: terminação em `?` ou `!` + texto curto (<160 chars) → `explicit_dialogue`
  - Padrão 4: `indirect_dialogue` (regex para "disse que", "que ia", "que não") → `indirect_dialogue`
  - Padrão 5: `narration` (default — 3ª pessoa, sem marcadores)
  - Padrão 6: `ambiguous` (texto que tem ?/! mas não encaixa em outros padrões)
- [x] 2.3 Adicionar testes unitários para UnitClassifier
  - `test_unit_classifier.py`: 12+ casos cobrindo todos os padrões
  - Casos do paste_1.txt: `Por que eu ia ceder`, `Eu me perguntei`, `Sou um jovem`, `Ele sorriu`, `Hã! Que raciocínio`

## 3. CandidateGenerator — Step 0 (1ª pessoa)

- [x] 3.1 Adicionar `_step_first_person` em `llm/candidate_generator.py`
  - Regex para marcadores: `eu me`, `por que eu`, `sou um/uma`, `minha`, `meu`
  - Retorna evidência `{"type": "FIRST_PERSON", "detail": "marker"}`
  - NÃO retorna speaker_id — apenas sinaliza que é diálogo implícito
- [x] 3.2 Adicionar Step 0 no pipeline de cascata (antes do Step 1)
- [x] 3.3 Atualizar versão do candidate generator em `config.CANDIDATE_GENERATOR_VERSION`
- [x] 3.4 Adicionar teste: `_step_first_person_detects_markers`

## 4. Turn Tracker

- [x] 4.1 Criar `llm/turn_tracker.py` com classe `TurnTracker`
- [x] 4.2 Implementar `track(scene_units: list[UnitClassification], active_speakers: list[str], focus_entity: str | None, scene_graph: SceneGraph | None) -> list[TurnAttribution]`
  - Regra 1: 0 ativos → todos `narrator`
  - Regra 2: 1 ativo → todos esse personagem
  - Regra 3: 2+ ativos → rotação circular nos units "dialogue"
  - Regra 4: `focus_entity` como anchor do primeiro turno
  - Regra 5: detectar mudança de bloco via `scene_graph.edges` ou `scene_graph.focus_entity`
  - Regra 6: units classificados como "narration" ou "indirect_dialogue" são ignorados (mantidos como narrator)
- [x] 4.3 Implementar `detect_block_transitions(units: list[UnitClassification], graph: SceneGraph | None) -> list[int]`
  - Índices de units que iniciam novos blocos (baseado em edges/focus_entity)
- [x] 4.4 Adicionar testes unitários para TurnTracker
  - `test_turn_tracker.py`: rotação circular, focus entity, 0/1/2+ personagens, block transitions
  - Casos do paste_1.txt: 2 personagens (young-man, office-lady), alternância correta

## 5. Modificação do Attribution (disambiguação)

- [x] 5.1 Modificar `attribution_scene()` em `llm/attribution.py`
  - Novos parâmetros: `resolved_units: list[TurnAttribution]`, `unit_classifications: list[UnitClassification]`
  - Filtrar apenas units "ambiguous" para LLM
  - Mesclar resultados do Turn Tracker + LLM
  - Manter unidades já resolvidas sem LLM
- [x] 5.2 Atualizar `_build_attribution_payload()` para incluir contexto de cena
  - `all_classifications`, `resolved_units`, `speakers` com perfis, `turn_history`
- [x] 5.3 Atualizar cache key: incluir `unit_classifier_version` e `turn_tracker_version`
- [x] 5.4 Reescrever `llm/prompts/attribution.md`
  - Instruções para disambiguação apenas
  - User payload com units já resolvidos + units ambíguos
  - Contexto de personagens, turn_history, scene_text
  - ~50 linhas, sem regras de diarização genéricas

## 6. Modificação do Pipeline (ollama_backend.py)

- [x] 6.1 Adicionar nova fase no `_process_scene()`: Unit Classification (Phase 3b)
- [x] 6.2 Adicionar nova fase: Turn Tracking (Phase 5b)
  - Executar após Unit Classification, antes de Attribution
  - Usar `active_speakers` do cast discovery + `focus_entity` do SceneGraph
- [x] 6.3 Modificar Phase 5 (Attribution): passar units já resolvidos + apenas ambíguos para LLM
- [x] 6.4 Modificar `_aggregate_scene_dialogues()` para mesclar Turn Attribution + LLM attribution
- [x] 6.5 Adicionar debug output: `debug_scene_<id>.json` por cena
  - `unit_classifications`, `turn_tracking`, `llm_disambiguation`, `qa_results`, métricas

## 7. QA por Cena

- [x] 7.1 Criar `check_speaker_diarization_scene()` em `llm/speaker_qa.py`
  - Recebe: lista de units classificados, atribuições (Turn Tracker + LLM), active_speakers
  - Regras:
    - Narrator collapse: se narrator_ratio > threshold em units "dialogue" → falha
    - Alternância: se 2+ ativos mas apenas 1 usado em units "dialogue" → falha se texto indica múltiplos
    - Closed-set: todos speakers (incluindo Turn Tracker) devem estar no allowed set
  - Retorna: severity (SKIP/MODERATE/RIGOROUS)
- [x] 7.2 Atualizar `_process_scene()` para usar QA por cena em vez de QA por unit
  - QA por unit ainda é executado para units ambíguos (após LLM)
  - QA por cena é executado após todos os units serem atribuídos
- [x] 7.3 Atualizar `qa_severity()` para reconhecer `TURN_TRACKER` como SKIP (determinístico, não erro)

## 8. Configuração e versions

- [x] 8.1 Adicionar `UNIT_CLASSIFIER_VERSION` em `config.py` (default: "v1")
- [x] 8.2 Adicionar `TURN_TRACKER_VERSION` em `config.py` (default: "v1")
- [x] 8.3 Bump `ATTRIBUTION_POLICY_VERSION` (invalida attribution caches existentes)
- [x] 8.4 Bump `CANDIDATE_GENERATOR_VERSION` (adicionar "-fp" para first-person)
- [x] 8.5 Adicionar `HYBRID_ATTRIBUTION_ENABLED` flag em config (default: True)

## 9. Testes integrados

- [x] 9.1 Criar `test_unit_classifier.py` — unit tests para classificação
- [x] 9.2 Criar `test_turn_tracker.py` — unit tests para turn tracker
- [x] 9.3 Criar `test_hybrid_attribution.py` — testes end-to-end do pipeline híbrido
  - Cena com 2 personagens, 20 units, 60% dialogue
  - Verificar: LLM calls reduzidas, alternância correta, narrator collapse detectado
- [x] 9.4 Validar com capítulo 5 (caso de teste: paste_1.txt)
  - Units 9, 11, 13, 15 classificados como "dialogue" (1ª pessoa)
  - Units 8, 10, 12 atribuídos corretamente (narrator, office-lady, young-man)
- [x] 9.5 Executar `uv run pytest` — garantir que todos os testes existentes passam

## 10. Limpeza e documentação

- [x] 10.1 Atualizar `AGENTS.md` com referência ao pipeline híbrido
- [x] 10.2 Adicionar comentários nos módulos novos (UnitClassifier, TurnTracker)
- [x] 10.3 Garantir que `llm/attribution.py` tem docstrings atualizadas
- [x] 10.4 Verificar linting: `uv run ruff check` (ou comando equivalente do projeto)
- [x] 10.5 Verificar type checking: `uv run pyright` (ou comando equivalente)
