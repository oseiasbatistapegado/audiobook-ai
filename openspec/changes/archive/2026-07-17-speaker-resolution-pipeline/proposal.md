## Why

O pipeline de interpretação de capítulos (`OllamaBackend.interpret_chapter`) envia o texto a uma única chamada LLM que deve simultaneamente: identificar personagens, resolver aliases, distinguir narração de fala, atribuir emoções, traduzir para pt-BR e gerar JSON válido. O modelo `qwen3:8b` falha nesses invariantes, gerando rejeição no QA e retries encadeados.

A causa-raiz é conceitual: **o pipeline mistura extração de estrutura com geração criativa**, transformando o 8B em juiz de tudo. A solução é adotar o paradigma de **compilação de linguagem natural** — quebrar o problema em etapas onde o código extrai estrutura e a LLM gera texto.

## What Changes

- **Scene Segmentation** como primeira etapa: divide capítulo em cenas (8–20 segmentos cada).
- **Cast Discovery** retorna apenas `id`, `name`, `aliases`, `participation` — nada de inferência.
- **CharacterProfile** (imutável, cross-capítulo) vs **SceneProfile** (temporal por cena).
- **InteractionGraph** substitui `relationships` nos perfis — relações são da cena, não do personagem.
- **Scene Graph** modela entidades, ações, diálogos, referências, foco narrativo.
- **CandidateGenerator** totalmente determinístico (regex → alias parser → pronoun resolver → scene graph → embedding como último recurso).
- **Speaker Attribution** recebe candidatos já preparados e evidence tipada; QA consome a evidence (EXPLICIT = skip, TURN_ORDER = moderado, EMBEDDING = rigoroso).
- **Interpretation** simplificada ao mínimo: `speaker_id` + `emotion constraints` + `adaptation policy`.
- **InterpretationState** como objeto único de estado (AST-like) compartilhado entre etapas.
- Caches separados de attribution e interpretação.

## Capabilities

### New Capabilities
- `speaker-resolution`: Scene Segmentation, CharacterProfile imutável vs SceneProfile temporal, InteractionGraph, CandidateGenerator determinístico (regex → parser → embedding fallback), attribution com evidence tipada, QA consome evidence.
- `scene-graph`: Scene Graph (entidades, ações, diálogos, referências, foco) como estrutura central de estado narrativo.
- `compilation-state`: InterpretationState como objeto único de estado (AST-like), compartilhado entre todas as etapas.

### Modified Capabilities
- `llm-interpretation`: Pipeline como pipeline de compilação (6 etapas LLM, 4 etapas determinísticas). Interpretation reduzida ao mínimo (speaker_id + emotion + adaptation policy). Caches separados.

## Impact

- **Arquitetura:** `OllamaBackend.interpret_chapter()` orquestra 10 etapas (6 LLM + 4 código). Novo `InterpretationState` como estado central.
- **Novos arquivos:** `llm/scene_segmenter.py`, `llm/scene_graph.py`, `llm/candidate_generator.py`, `llm/interpretation_state.py`, `llm/attribution.py`, `llm/sanitizer.py`, `llm/prompts/attribution.md`, `embeddings/speaker.py`.
- **Modificados:** `models/cast.py` (CharacterProfile/SceneProfile/InteractionGraph), `models/llm.py` (status: "needs_review"), `llm/ollama_backend.py` (orquestração), `llm/speaker_qa.py` (consume evidence).
- **Configuração:** Novas constantes (`EMBEDDING_MODEL`, `SPEAKER_RESOLUTION_TOP_K`, `QA_CORRECTION_MAX_ATTEMPTS`, `ATTRIBUTION_EMBEDDING_GAP_THRESHOLD`).
- **Dependencies:** `sentence-transformers` via `uv sync --extra speaker-resolution`.
