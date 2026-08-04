## 1. Schema e modelos

- [x] 1.1 Manter `ChapterCastEntry` em `models/cast.py` com apenas `id`, `name`, `aliases`, `participation` (sem `speaker_profile`)
- [x] 1.2 Criar modelo `CharacterProfile` em `models/cast.py` com `id`, `name`, `aliases`, `gender`, `role` (POV/secondary/teacher/etc.), `known_names: list[str]`
- [x] 1.3 Criar modelo `SceneProfile` em `models/cast.py` com `mood: str | None`, `speech_patterns: list[str]`, `interactions: list[str]`, `active_actions: list[str]`
- [x] 1.4 Criar modelo `InteractionEdge` em `models/cast.py` com `source: str`, `target: str | None`, `type: str`, `scene_id: str`
- [x] 1.5 Criar modelo `EvidenceEntry` em `models/cast.py` com `type: str` (EXPLICIT/TURN_ORDER/SCENE_CONTEXT/ALIAS_MATCH/EMBEDDING/RELATIONSHIP), `detail: str`
- [x] 1.6 Criar modelo `DialogueAttribution` em `models/cast.py` com `primary: str`, `ranked_candidates: list[str]`, `evidence: list[EvidenceEntry]`, `reason: str`
- [x] 1.7 Criar modelo `AttributionResponse` em `models/cast.py` com `attributions: list[DialogueAttribution]`
- [x] 1.8 Criar modelo `SegmentClassification` em `models/cast.py` com `text: str`, `classification: str` (explicit_dialogue/indirect_dialogue/narration), `is_indirect: bool`
- [x] 1.9 Criar modelo `InterpretedDialogue` em `models/llm.py` com campo opcional `status: str | None` (para `status: "needs_review"`)
- [x] 1.10 Validar modelos com `pydantic` (testes unitários em `tests/test_models.py` ou arquivo dedicado)

## 2. Scene Segmentation

- [x] 2.1 Criar `llm/scene_segmenter.py` com classe `SceneSegmenter`:
  - `segment(text: str) -> list[Scene]`
  - `Scene` em `models/scene.py` com `scene_id: str`, `units: list[str]`, `text: str`
- [x] 2.2 Heurística de detecção: mudanças de foco (novo personagem), entrada/saída (`entrou`, `saiu`, `deixou`), quebra de diálogo, mudança de tempo/lugar
- [x] 2.3 Cada cena tem tipicamente 8–20 segmentos
- [x] 2.4 Testar com capítulos de 50, 100, 120+ segmentos (validar divisão por cena)
- [x] 2.5 Scene Segmentation é **totalmente determinística** (mesmo input → mesma output)

## 3. Cast Discovery (Pass 1 — apenas ids)

- [x] 3.1 Validar que `_discover_chapter_chunk` em `ollama_backend.py` retorna apenas `id`, `name`, `aliases`, `participation` (sem `speaker_profile`)
- [x] 3.2 Atualizar `discover_cast.md`: instruir LLM a retornar **apenas** ids, names, aliases, participation — **nada** de inferências persistentes
- [x] 3.3 Manter cache de cast discovery com chave = `chapter_hash + cast_policy_version`
- [x] 3.4 Garantir que cast discovery legacy (sem `speaker_profile`) é compatível com novo pipeline
- [x] 3.5 O Cast Discovery **não** inventa conhecimento persistente: "fria", "agressiva" não são traits do personagem

## 4. CharacterProfile Manager

- [x] 4.1 Criar `llm/profile_manager.py` com função `resolve_character_profile(character_id: str, name: str, aliases: list[str]) -> CharacterProfile`
- [x] 4.2 O `CharacterProfile` é cacheado por `character_id` (não por capítulo) — persiste cross-capítulo
- [x] 4.3 O `CharacterProfile` contém apenas **fatos imutáveis**: `id`, `name`, `aliases`, `gender`, `role`, `known_names`
- [x] 4.4 Se o `character_id` já existia em capítulo anterior, reutilizar o perfil (cache hit)
- [x] 4.5 Se novo personagem, criar `CharacterProfile` com `role: "secondary"` (default)
- [x] 4.6 `CharacterProfile` é serializável: `model_dump_json()`
- [x] 4.7 Persistir `character_profiles.json` em `out/<book_id>/` para debug

## 5. Scene Graph Builder

- [x] 5.1 Criar `llm/scene_graph.py` com modelos Pydantic:
  - `EntityNode` com `id: str`, `name: str`, `first_seen: int`, `last_seen: int`
  - `InteractionEdge` com `source: str`, `target: str | None`, `type: str`, `scene_id: str`
  - `SceneGraph` com `scene_id: str`, `entities: list[EntityNode]`, `edges: list[InteractionEdge]`, `focus_entity: str | None`, `turn_order: list[dict]`, `entity_actions: list[dict]`
- [x] 5.2 Criar função `build_scene_graph(scene_units: list[dict], character_profiles: dict[str, CharacterProfile], classifications: list[str]) -> SceneGraph`
- [x] 5.3 O `build_scene_graph` é chamado **após** a Attribution de cada cena, com os resultados da Attribution + classificador 3 classes
- [x] 5.4 O Scene Graph Builder é 100% código determinístico (regex + parser), **não usa LLM**
- [x] 5.5 Extrair `focus_entity` do Scene Graph: personagem mais frequente em units de texto (não apenas diálogos)
- [x] 5.6 Testar com cenários de entrada/saída de personagens, ações narradas, alternância de foco
- [x] 5.7 Testar com "Sorriu." → entity_action com `classification: "narration"` e `focus_entity` correto
- [x] 5.8 Scene Graph é serializável: `model_dump_json()`

## 6. Classificação 3 classes de segmento

- [x] 6.1 Criar função `classify_segment(text: str) -> str` em `llm/sanitizer.py` retornando `"explicit_dialogue"`, `"indirect_dialogue"`, ou `"narration"`
- [x] 6.2 Critérios: EXPLICIT (aspas, travessão, atribuição explícita com verbos de fala), INDIRECT ("Ele disse que...", `is_indirect=true`), NARRATION (prosa pura)
- [x] 6.3 Reutilizar `is_quoted_turn()` de `speaker_qa.py` para detecção de aspas/travessão
- [x] 6.4 Criar função `coerce_speaker_from_classification(attribution: DialogueAttribution, classification: str) -> DialogueAttribution` para mapear classification → speaker_id
- [x] 6.5 Testar com casos de 1ª pessoa, travessão, aspas, discurso indireto, e prosa pura

## 7. Candidate Generator totalmente determinístico

- [x] 7.1 Criar `llm/candidate_generator.py` com função `generate_candidates(unit_text: str, character_profiles: dict[str, CharacterProfile], scene_graph: SceneGraph | None) -> list[Candidate]`
- [x] 7.2 Pipeline em cascata:
  - Step 1: **Nome explícito** — regex (`[A-ZÁÉÍÓÚÂÊÔÃÕÜ][\w'-]+` precedido por `disse`, `respondeu`, `perguntou`) → lookup em `character_profiles`
  - Step 2: **Alias explícito** — regex sobre `descriptive_aliases` do CharacterProfile → match no texto
  - Step 3: **Pronome** — parser de corefência (`ele`/`ela`) → lookup em `character_profiles` por gender
  - Step 4: **Entity em foco** — `focus_entity` do Scene Graph → candidato primário
  - Step 5: **Embedding** — fallback: `resolve_descriptive_aliases` com `paraphrase-multilingual-MiniLM-L12-v2`
- [x] 7.3 `Candidate` model com `speaker_id: str`, `score: float`, `evidence: list[EvidenceEntry]`
- [x] 7.4 Step 5 (embedding) é chamado **apenas** se steps 1–4 falharem em resolver
- [x] 7.5 O cache de embedding é por `character_id` (não por capítulo): `save_embedding(speaker_id, embedding)`, `load_embedding(speaker_id)`
- [x] 7.6 Se embedding cache hit, reutilizar. Se miss (personagem novo), calcular e salvar.
- [x] 7.7 Testar com casos de nome explícito, alias descritivo, pronome, entity em foco, e fallback embedding
- [x] 7.8 Candidate Generator é 100% código — **não usa LLM**

## 8. Attribution por cena

- [x] 8.1 Criar `llm/attribution.py` com função `attribution_scene(units: list[InterpretUnit], candidates: list[Candidate], scene_graph: SceneGraph) -> list[DialogueAttribution]`
- [x] 8.2 Integrar ao `OllamaBackend` no método `_attribution_scene` que chama Ollama com o prompt dedicado
- [x] 8.3 O `_attribution_scene` recebe `candidates` (do CandidateGenerator) e `scene_graph` no user payload
- [x] 8.4 Batching adaptativo: cada cena (8–20 segmentos) é uma chamada LLM independente
- [x] 8.5 Implementar retry por cena no attribution (até `LLM_INTERPRET_MAX_ATTEMPTS`) com erro injetado no prompt
- [x] 8.6 Fallback por cena: se attribution falha, retornar atribuições com `primary="narrator"`, `ranked_candidates=["narrator"]`, `evidence=[{type: "EXPLICIT", detail: "attribution_failed"}]`
- [x] 8.7 Cache de attribution com chave = `scene_hash + character_profile_hash + candidate_generator_version + attribution_policy_version`
- [x] 8.8 O prompt de attribution instrui: `primary`, `ranked_candidates`, `evidence` (lista de `{type, detail}`), `reason`

## 9. Prompt de attribution

- [x] 9.1 Criar `llm/prompts/attribution.md` com instruções focadas exclusivamente em classificação de falantes (~40 linhas)
- [x] 9.2 O prompt instrui o modelo a retornar: `primary` (speaker_id principal), `ranked_candidates` (lista ordenada), `evidence` (lista de `{type, detail}`), `reason` (texto livre curto)
- [x] 9.3 O prompt instrui classificador 3 classes (explicit_dialogue, indirect_dialogue, narration)
- [x] 9.4 Adicionar constante `LLM_ATTRIBUTION_PROMPT_FILE` em `config.py`
- [x] 9.5 Validar que `attribution.md` tem menos linhas que `interpret_chapter.md`
- [x] 9.6 Garantir que o prompt instrui: um speaker por turno, proibição de misturar falantes, proibição de speech-tags

## 10. InterpState (estado central)

- [x] 10.1 Criar `llm/interpretation_state.py` com classe `InterpretationState`:
  - `scenes: list[Scene]` (scene segmentation)
  - `characters: list[Character]` (cast discovery)
  - `character_profiles: dict[str, CharacterProfile]` (perfis imutáveis)
  - `scene_graphs: dict[str, SceneGraph]` (scene_id → grafo)
  - `candidates: dict[str, list[Candidate]]` (scene_id → candidatos)
  - `attributions: dict[str, list[DialogueAttribution]]` (scene_id → atribuições)
  - `qa_status: dict[str, list[str]]` (scene_id → status per unit)
  - `rejected_units: set[tuple[str, int]]` (scene, unit) com needs_review
  - `interpretations: dict[str, list[Dialogue]]` (scene_id → diálogos)
- [x] 10.2 O `InterpretationState` é o único objeto de estado compartilhado entre todas as etapas
- [x] 10.3 Cada etapa adiciona dados ao state sem modificar dados anteriores (imutabilidade por fase)
- [x] 10.4 O state é serializável por cena: `state.dump_scene(scene_id)` → JSON
- [x] 10.5 Testar serialização: `InterpretationState.model_dump_json()` retorna JSON válido
- [x] 10.6 Persistir `interpretation_state.json` em `out/<book_id>/` para debug

## 11. QA consome evidence

- [x] 11.1 Modificar `llm/speaker_qa.py` para consumir `evidence.type`:
  - Mapeamento: `EXPLICIT → skip`, `TURN_ORDER → moderado`, `SCENE_CONTEXT → moderado`, `ALIAS_MATCH → moderado`, `EMBEDDING → rigoroso se gap ≤ 0.20`, `RELATIONSHIP → moderado`
- [x] 11.2 Função `qa_severity(evidence: list[EvidenceEntry]) -> str` retorna `"skip" | "moderate" | "rigorous"`
- [x] 11.3 QA rigoroso aplica todos os invariantes (mesmo comportamento atual)
- [x] 11.4 QA moderado aplica invariantes de narração + speech-tag (skip dominance)
- [x] 11.5 QA skip passa direto (sem validação adicional)
- [x] 11.6 Retirar lógica de gap de embedding como único critério de rigor (agora evidence.type é a fonte primária)
- [x] 11.7 Manter fallback de gap de embedding como critério secundário para `EMBEDDING`

## 12. QA por unidade isolada com `status: "needs_review"`

- [x] 12.1 Modificar `OllamaBackend` para processar units em loop individual (por cena)
- [x] 12.2 Para cada unit: calcular `qa_severity(evidence)`. Se `rigorous`, aplicar todos invariantes.
- [x] 12.3 Quando QA falha, injetar erro específico no prompt de retry DAQUELA unidade (até `QA_CORRECTION_MAX_ATTEMPTS`)
- [x] 12.4 Se todas as tentativas esgotadas, criar `Dialogue` com `{status: "needs_review", speaker_id: null, text: original, emotion: "neutral", rejection_reason: "..."}`
- [x] 12.5 Emitir log de info com capítulo, unidade, e motivo da rejeição
- [x] 12.6 Garantir que units bem-sucedidas continuam processando mesmo após unit needs_review
- [x] 12.7 Validar que `_try_validate` no backend passa `unit_text` e `story_state` para `check_speaker_diarization`

## 13. InterpState persist por cena

- [x] 13.1 O `InterpretationState` é persistido por cena (não por capítulo): `out/<book_id>/chapters/<chapter_id>/state_scene_<scene_id>.json`
- [x] 13.2 Ao iniciar processamento de capítulo, o state é carregado (ou criado vazio)
- [x] 13.3 Ao final de cada cena, o state é serializado e persistido
- [x] 13.4 Ao final do capítulo, o state completo é persistido em `out/<book_id>/state.json`
- [x] 13.5 State é carregado para resume: se um capítulo foi parcialmente processado, retoma da cena anterior

## 14. InterpState debug serializável

- [x] 14.1 `InterpretationState.dump_scene(scene_id: str) -> dict` retorna o state serializado para debug
- [x] 14.2 Cada cena gera um JSON debug em `out/<book_id>/chapters/<chapter_id>/debug_scene_<scene_id>.json`
- [x] 14.3 O JSON debug contém: `scenes`, `character_profiles`, `scene_graph`, `candidates`, `attributions`, `qa_status`
- [x] 14.4 O debug JSON é gerado **apenas** se flag `DEBUG_STATE_DUMP=True` (padrão: `False` em produção)

## 15. Interpretação Pass simplificada

- [x] 15.1 Modificar `_build_user_payload` em `ollama_backend.py` para incluir **apenas** `speaker_id` + `emotion_constraints` + `adaptation_policy` + `unit_text`
- [x] 15.2 Remover do user payload: perfis de personagens, scene graph, conversation state, aliases, relationships, speaking style, role
- [x] 15.3 Simplificar `interpret_chapter.md`: remover **todas** as regras de diarização (já resolvidas)
- [x] 15.4 Garantir que `interpret_chapter.md` instrui **apenas** a usar o `speaker_id` fornecido, formatar com emoção e adaptar para pt-BR
- [x] 15.5 Validar que `interpret_chapter.md` tem menos ou igual linhas que `attribution.md`
- [x] 15.6 Cache de interpretação com chave = `scene_hash + attribution_cache_key + prompt_version + adaptation_policy_version`
- [x] 15.7 Separar `_read_attribution_cache`/`_write_attribution_cache` de `_read_cache`/`_write_cache` (dois caches independentes, keyed por cena)

## 16. Downstream TTS detecta status: needs_review

- [x] 16.1 Modificar `gpu/orchestrate.py` (ou equivalente) para detectar `status: "needs_review"` nos Diálogos
- [x] 16.2 Unidades com `status: "needs_review"` são **omitidas** do merge de áudio (não geram audio)
- [x] 16.3 O `text: original` é preservado para debug/revisão
- [x] 16.4 Emitir log de warning se unidades needs_review > 5% do capítulo
- [x] 16.5 Garantir que `status` é opcional e default para `None` (backwards compat com unidades sem rejection)

## 17. Embeddings como retriever (fallback)

- [x] 17.1 Criar `embeddings/__init__.py` como novo sub-pacote
- [x] 17.2 Criar `embeddings/speaker.py` com classe `SpeakerEmbeddingService`:
  - `load(model_name: str) -> SpeakerEmbeddingService`
  - `encode(text: str) -> list[float]`
  - `cosine_similarity(a: list[float], b: list[float]) -> float`
  - `resolve_descriptive_aliases(text: str, profiles: list[CharacterProfile], top_k: int) -> list[tuple[str, float]]`
  - `save_embedding(speaker_id: str, embedding: list[float])`
  - `load_embedding(speaker_id: str) -> list[float] | None`
- [x] 17.3 O cache de embeddings é por **personagem**: `save_embedding(speaker_id, embedding)` e `load_embedding(speaker_id)`
- [x] 17.4 Se embedding cache hit para personagem, reutilizar. Se miss (personagem novo), calcular e salvar.
- [x] 17.5 Adicionar `sentence-transformers` como dependência opcional em `pyproject.toml` (`uv sync --extra speaker-resolution`)
- [x] 17.6 Se embedding falhar, degradar silenciosamente para CandidateGenerator steps 1–4 (sem erro fatal)

## 18. Fingerprint de cache

- [x] 18.1 Garantir que `attribution_cache_key` é keyed por `scene_hash` (não `chapter_hash`)
- [x] 18.2 Garantir que `interpretation_cache_key` é keyed por `scene_hash`
- [x] 18.3 Adicionar funções em `llm/cache.py`:
  - `attribution_cache_key(scene: Scene, character_profiles_hash: str, candidate_generator_version: str, attribution_policy_version: str) -> str`
  - `interpretation_cache_key(scene: Scene, attribution_cache_key: str, prompt_version: str, adaptation_policy_version: str) -> str`
- [x] 18.4 Garantir que mudança de `ATTRIBUTION_POLICY_VERSION` invalida apenas attribution caches
- [x] 18.5 Garantir que mudança de `INTERPRETATION_POLICY_VERSION` invalida apenas interpretation caches

## 19. Configuração

- [x] 19.1 Adicionar constantes em `config.py`: `LLM_ATTRIBUTION_PROMPT_FILE`, `QA_CORRECTION_MAX_ATTEMPTS` (default: 3), `SPEAKER_RESOLUTION_TOP_K` (default: 3)
- [x] 19.2 Adicionar constante `ATTRIBUTION_EMBEDDING_GAP_THRESHOLD` (default: `0.20`)
- [x] 19.3 Adicionar constante `EMBEDDING_MODEL` (default: `"paraphrase-multilingual-MiniLM-L12-v2"`)
- [x] 19.4 Adicionar flag `SPEAKER_RESOLUTION_V2_ENABLED` (default: `True`) para rollback seguro
- [x] 19.5 Adicionar constante `DEBUG_STATE_DUMP` (default: `False`) para debug serializável
- [x] 19.6 Adicionar constantes de versão: `ATTRIBUTION_POLICY_VERSION` (default: `"v1"`), `INTERPRETATION_POLICY_VERSION` (default: `"v1"`), `CAST_POLICY_VERSION` (default: `"v1"`)

## 20. Testes

- [x] 20.1 Testes unitários de `SceneSegmenter.segment()` com capítulos de 50, 100, 120+ segmentos
- [x] 20.2 Testes unitários de `classify_segment` com prosa 1ª pessoa, travessão, aspas, discurso indireto, prosa pura
- [x] 20.3 Testes unitários de `build_scene_graph` com cenários de entrada/saída, ações narradas, alternância de foco
- [x] 20.4 Testes unitários de `generate_candidates` (determinístico) com nome explícito, alias, pronome, entity em foco, fallback embedding
- [x] 20.5 Testes unititários de `attribution_scene` com atribuição explícita e diálogo encadeado
- [x] 20.6 Testes de `qa_severity(evidence)`: EXPLICIT → skip, TURN_ORDER → moderado, EMBEDDING gap ≤ 0.20 → rigoroso
- [x] 20.7 Testes de QA por unidade isolada: unidade 54 falha, 1-53 e 55+ passam
- [x] 20.8 Testes de integração: pipeline completo (Scene Segmentation → Cast Discovery → CharacterProfile → Scene Graph → Candidate Generator → Attribution → QA → Interpretation)
- [x] 20.9 Manter fixtures existentes de regressão (ch-011, ch-004) passando no novo pipeline
- [x] 20.10 Testes de que `status: "needs_review"` é omitido pelo downstream TTS
- [x] 20.11 Testes de serialização: `InterpretationState.model_dump_json()` retorna JSON válido

## 21. Integração e migração

- [x] 21.1 Atualizar `OllamaBackend.interpret_chapter()` para orquestrar novo fluxo: Scene Segmentation → Cast Discovery → CharacterProfile → Scene Graph → Candidate Generator → Attribution → QA → Interpretation → Validation → TTS
- [x] 21.2 Integrar `InterpretationState` como único objeto de estado
- [x] 21.3 Separar `attribution_cache` de `interpretation_cache` (dois diretórios/métodos independentes, keyed por cena)
- [x] 21.4 Validar que o pipeline legacy (sem speaker resolution) ainda funciona quando `SPEAKER_RESOLUTION_V2_ENABLED=False`
- [x] 21.5 Atualizar `pyproject.toml` com dependência opcional `speaker-resolution`
- [x] 21.6 Atualizar `AGENTS.md` com descrição do novo pipeline de compilação NL
- [x] 21.7 Documentar mudanças de fingerprint no changelog (invalida caches existentes)
- [x] 21.8 Executar `uv run pytest` e garantir que todos os testes passam
