## Purpose

O `SceneGraph` modela a estrutura narrativa de cada cena: entidades presentes, ações, diálogos, referências, foco narrativo. É construído por código determinístico (não pela LLM) e alimentado pelo classificador 3 classes (`llm/sanitizer.py`). Resolve ambiguidades que apenas speaker tracking não consegue — ex.: "Sorriu." é narrator mas pertence à Horikita.

O `SceneGraph` substitui o antigo `SceneTracker` como estrutura central de estado narrativo.

## Requirements

### Requirement: Scene Graph modela entidades, ações e foco

O módulo `SceneGraph` (em `llm/scene_graph.py`) SHALL modelar a estrutura narrativa de uma cena:

- `entities`: lista de personagens presentes na cena (detectados por regex + character profiles)
- `edges`: lista de `InteractionEdge` (relações direcionadas: `responde`, `interrompe`, `olha`, `fala_com`)
- `focus_entity`: personagem em foco narrativo (quem está sendo descrito no momento)
- `turn_order`: sequência de falas por cena (`{unit_index, speaker_id, type}`)
- `entity_actions`: ações descritas no texto (`{entity, action, unit_index, classification}`)

O Scene Graph é construído após a classificação 3 classes e a attribution de cada cena.

#### Scenario: Scene Graph identifica personagens em cena
- **WHEN** uma cena contém "Horikita entrou. Ela sentou."
- **THEN** o `entities` inclui `horikita_suzune` e `focus_entity` é `horikita_suzune`

#### Scenario: Scene Graph vincula ação a entidade
- **WHEN** uma cena contém "Sorriu. — Tudo bem."
- **THEN** o `entity_actions` inclui `{"entity": "horikita_suzune", "action": "sorriu"}` com `classification: "narration"`

### Requirement: InteractionGraph substitui relationships nos perfis

O sistema NÃO deve armazenar relações interpersonais (`relationships`) no `CharacterProfile` (imutável). Relações são **dados da cena**, não do personagem.

Em vez de `relationships` no perfil, o sistema usa `InteractionEdge` no `SceneGraph`:
- `source: str` — character_id do falante
- `target: str | None` — character_id do receptor (null para ações não-direcionadas)
- `type: str` — tipo de interação (`responde`, `interrup`, `olha`, `fala_com`, `interrompe`)
- `scene_id: str` — cena à qual a interação pertence

As edges são extraídas do texto por regex sobre atribuições explícitas (`disse X`, `respondeu a Y`, `perguntou para Z`) e do classificador 3 classes.

#### Scenario: InteractionEdge extrai relação de texto
- **WHEN** a cena contém `— Você está atrasado, disse Horikita a Ayanokoji.`
- **THEN** o `edges` inclui `InteractionEdge(source="horikita_suzune", target="ayanokoji_kiyotaka", type="responde")`

#### Scenario: SceneProfile contém interações temporais
- **WHEN** uma cena contém interações entre personagens
- **THEN** o `SceneProfile` (temporal) inclui `interactions: ["responde a Ayanokoji", "interrompe Hirata"]`
- **NÃO** o `CharacterProfile` (imutável)

### Requirement: Scene Graph é alimentado pelo classificador e attribution

O Scene Graph Builder é chamado após a Attribution de cada cena. Ele recebe:
- As unidades processadas pela Attribution (`unit_index`, `text`, `primary`, `ranked_candidates`)
- O classificador 3 classes (para identificar `is_indirect` e `narration`)
- O texto original das unidades (para extrair entity actions)
- O `character_profiles` (para resolver nomes → stable_ids)

O Scene Graph Builder retorna seu grafo ao `InterpretationState` para alimentar o `candidate_generator` de cenas subsequentes.

#### Scenario: Scene Graph Builder é chamado após attribution
- **WHEN** a Attribution de uma cena termina
- **THEN** o Scene Graph Builder é chamado com os resultados da Attribution + classificador
- **THEN** o Scene Graph Builder retorna `entities`, `edges`, `focus_entity`, `turn_order`, `entity_actions`

### Requirement: Scene Graph ajuda a resolver narrador → personagem

O Scene Graph SHALL detectar quando um segmento classificado como `narration` pertence a uma entidade ativa. Quando `focus_entity` é `horikita_suzune` e um segmento de `narration` contém verbos de ação (`sorriu`, `entrou`, `sentou`, `andou`), o `candidate_generator` recebe como evidência do tipo `SCENE_CONTEXT`: `{"type": "SCENE_CONTEXT", "detail": "focus_entity=horikita_suzune"}`.

**Nota importante:** Mesmo com `SCENE_CONTEXT`, o `primary` da attribution para segmentos de `narration` (sem aspas/travessão) é `narrator`. A diferença é que o `candidate_generator` sabe que a narração pertence à entidade ativa, o que ajuda a `Interpretation Pass` a escolher a emoção apropriada.

#### Scenario: Narration de entidade ativa recebe SCENE_CONTEXT
- **WHEN** `focus_entity` é `horikita_suzune` e a unidade contém `Ela sorriu.`
- **THEN** o candidate_generator retorna evidence com `{"type": "SCENE_CONTEXT", "detail": "focus_entity=horikita_suzune"}`

#### Scenario: Narration de entidade inexistente é narrator genérico
- **WHEN** `focus_entity` é `null` e a unidade contém `O dia estava bonito.`
- **THEN** o candidate_generator retorna evidence com `{"type": "TURN_ORDER", "detail": "sem entidades ativas"}`

### Requirement: Scene Graph é resetado entre capítulos

O Scene Graph NÃO mantém estado entre capítulos. Cada capítulo inicia com grafo vazio (`entities: []`, `edges: []`, `focus_entity: null`). Isso evita que entidades de capítulos anteriores contaminem a attribution de capítulos novos.

#### Scenario: Scene Graph é resetado entre capítulos
- **WHEN** um novo capítulo começa a ser processado
- **THEN** o Scene Graph inicia com estado vazio

#### Scenario: Scene Graph mantém estado dentro do capítulo
- **WHEN** um capítulo tem 10 cenas
- **THEN** o `entities` da cena 7 inclui entidades que entraram na cena 3

### Requirement: Scene Graph é serializável para debug

O `SceneGraph` SHALL ser serializável via `model_dump_json()` (Pydantic). Cada cena gera um JSON do grafo que pode ser persistido sob `out/<book_id>/chapters/<chapter_id>/scene_graph_<scene_id>.json` para debug.

#### Scenario: Scene Graph é serializável
- **WHEN** uma cena é processada
- **THEN** `scene_graph.model_dump_json()` retorna JSON válido com `entities`, `edges`, `focus_entity`, `turn_order`, `entity_actions`
