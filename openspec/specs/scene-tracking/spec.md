## Purpose

Manter o estado narrativo entre cenas: quais personagens estão presentes, quem está em foco, ordem dos falantes, ações descritas. O Scene Tracker resolve ambiguidades que apenas speaker tracking não consegue — ex.: "Sorriu." é narrator mas pertence à Horikita.

## Requirements

### Requirement: Scene Tracker mantém active_entities e focus_entity

O módulo `SceneTracker` (em `llm/scene_tracker.py`) SHALL rastrear entidades ativas na cena atual:
- `active_entities`: lista de personagens presentes na cena
- `focus_entity`: personagem em foco narrativo (quem está sendo descrito)
- `entity_actions`: ações descritas no texto (`{"entity": "horikita", "action": "sorriu"}`)

O Scene Tracker é atualizado a cada cena processada e é retornado ao `SpeakerResolver` para alimentar o `resolved_context` de cenas subsequentes.

#### Scenario: Scene Tracker identifica personagens em cena
- **WHEN** uma cena contém "Horikita entrou. Ela sentou."
- **THEN** o `active_entities` inclui `horikita_suzune` e `focus_entity` é `horikita_suzune`

#### Scenario: Scene Tracker vincula ação a entidade
- **WHEN** uma cena contém "Sorriu. — Tudo bem."
- **THEN** o `entity_actions` inclui `{"entity": "horikita_suzune", "action": "sorriu"}` e o attribution subsequent recebe este contexto

### Requirement: Scene Tracker mantém turn_order

O Scene Tracker SHALL manter a sequência de falantes por cena:
- `turn_order`: lista de `{unit: int, speaker: str, type: str}` ordenada por índice de unidade
- `type` é inferido pela classification 3 classes: `explicit_dialogue` → `"dialogue"`, `narration` → `"narration"`, `indirect_dialogue` → `"indirect"`

O `turn_order` é retornado ao `SpeakerResolver` como parte do `resolved_context`.

#### Scenario: Turn order inclui unidades de fala
- **WHEN** uma cena tem 5 unidades com falas de Horikita e Ayanokoji alternados
- **THEN** o `turn_order` contém 5 entries ordenados por índice de unidade com `speaker` e `type` corretos

### Requirement: Scene Tracker é alimentado pelo classificador e attribution

O Scene Tracker é chamado após a Attribution de cada cena. Ele recebe:
- As unidades processadas pela Attribution (`unit_index`, `text`, `primary`, `ranked_candidates`)
- O classificador 3 classes (para identificar `is_indirect` e `narration`)
- O texto original das unidades (para extrair entity actions)

O Scene Tracker retorna seu estado ao `SpeakerResolver` para alimentar o `resolved_context` da próxima cena.

#### Scenario: Scene Tracker é chamado após attribution
- **WHEN** a Attribution de uma cena termina
- **THEN** o Scene Tracker é chamado com os resultados da Attribution + classificador
- **THEN** o Scene Tracker retorna `active_entities`, `focus_entity`, `turn_order`, `entity_actions`

### Requirement: Scene Tracker é resetado entre capítulos

O Scene Tracker NÃO mantém estado entre capítulos. Cada capítulo inicia com estado vazio (`active_entities: []`, `focus_entity: null`). Isso evita que entidades de capítulos anteriores contaminem a attribution de capítulos novos.

#### Scenario: Scene Tracker é resetado entre capítulos
- **WHEN** um novo capítulo começa a ser processado
- **THEN** o Scene Tracker inicia com estado vazio

#### Scenario: Scene Tracker mantém estado dentro do capítulo
- **WHEN** um capítulo tem 10 cenas
- **THEN** o `active_entities` da cena 7 inclui entidades que entraram na cena 3

### Requirement: Scene Tracker ajuda a resolver narrador → personagem

O Scene Tracker SHALL detectar quando um segmento classificado como `narration` pertence a uma entidade ativa. Quando `focus_entity` é `horikita_suzune` e um segmento de `narration` contém verbos de ação (`sorriu`, `entrou`, `sentou`, `andou`), o attribution recebe como `evidence` do tipo `SCENE_CONTEXT`: `{"type": "SCENE_CONTEXT", "detail": "focus_entity=horikita_suzune"}`.

**Nota importante:** Mesmo com `SCENE_CONTEXT`, o `primary` do attribution para segmentos de `narration` (sem aspas/travessão) é `narrator`. A diferença é que o attribution sabe que a narração pertence à entidade ativa, o que ajuda a `Interpretation Pass` a escolher a emoção apropriada.

#### Scenario: Narration de entidade ativa recebe SCENE_CONTEXT
- **WHEN** `focus_entity` é `horikita_suzune` e a unidade contém `Ela sorriu.`
- **THEN** o attribution retorna `primary: "narrator"`, evidence contendo `{"type": "SCENE_CONTEXT", "detail": "focus_entity=horikita_suzune"}`

#### Scenario: Narration de entidade inexistente é narrator genérico
- **WHEN** `focus_entity` é `null` e a unidade contém `O dia estava bonito.`
- **THEN** o attribution retorna `primary: "narrator"`, evidence contendo `{"type": "TURN_ORDER", "detail": "sem entidades ativas"}`
