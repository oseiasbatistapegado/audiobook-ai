## MODIFIED Requirements

### Requirement: Classificação 3 classes de segmento (estendido)

O sistema SHALL classificar cada segmento como `explicit_dialogue`, `indirect_dialogue`, ou `narration` por código determinístico (não pela LLM). O classificador categoriza:

- **EXPLICIT_DIALOGUE**: texto entre aspas (`"`, `""`), travessão (`—`, `–`), ou contendo atribuição explícita (disse, perguntou, respondeu, gritou, sussurrou)
- **INDIRECT_DIALOGUE**: discurso indireto ("Ele disse que iria embora.") — marcado com flag `is_indirect=true`
- **NARRATION**: prosa pura, descrição de cena, interior monologue

**ADICIONADO**: O classificador SHALL **também** classificar unidades de diálogo sem marcação explícita usando marcadores de 1ª pessoa, terminação em `?`/`!`, e vocativos. Unidades com `eu`, `meu`, `minha`, `sou (um/uma)`, `por que eu` devem ser classificadas como `dialogue` mesmo sem aspas/travessão.

O classificador é implementado em `llm/unit_classifier.py`. Não depende da LLM.

#### Scenario: Aspas são classificadas como explicit_dialogue
- **WHEN** a unidade contém `"Você está atrasado."`
- **THEN** o segmento é classificado como `explicit_dialogue`

#### Scenario: Travessão é classificado como explicit_dialogue
- **WHEN** a unidade contém `— Você está atrasado.`
- **THEN** o segmento é classificado como `explicit_dialogue`

#### Scenario: 1ª pessoa é classificada como dialogue sem aspas
- **WHEN** a unidade contém `Por que eu ia ceder o assento?` sem aspas
- **THEN** o segmento é classificado como `explicit_dialogue` (dialogue implícito por 1ª pessoa)

#### Scenario: "Sou um jovem" é classificado como dialogue
- **WHEN** a unidade contém `Sou um jovem saudável e não teria inconveniência`
- **THEN** o segmento é classificado como `explicit_dialogue` (dialogue implícito por marcador 1ª pessoa)

#### Scenario: Prosa pura em 3ª pessoa é classificada como narration
- **WHEN** a unidade contém `Ele sorriu amplamente e cruzou as pernas.`
- **THEN** o segmento é classificado como `narration` (3ª pessoa, sem marcador de diálogo)

#### Scenario: Discurso indireto é classificado como indirect_dialogue
- **WHEN** a unidade contém `Ele disse que não ia mais.`
- **THEN** o segmento é classificado como `indirect_dialogue` com `is_indirect=true`

### Requirement: CandidateGenerator — novo Step 0 (1ª pessoa)

O sistema SHALL incluir um módulo `CandidateGenerator` (`llm/candidate_generator.py`) que produz candidatos de speaker para cada segmento, **totalmente por código** (sem LLM). Pipeline em cascata:

0. **Marcador de 1ª pessoa** (NOVO): regex para `eu me`, `por que eu`, `sou um/uma`, `minha`, `meu` → se encontrado, marca o unit como **dialogue implícito**. O candidate_generator retorna `narrator` como candidato alternativo (para a interpretação saber que é diálogo, não narrator), mas a atribuição de speaker real será resolvida pelo Turn Tracker.
1. **Nome explícito** — regex no texto (`[A-ZÁÉÍÓÚÂÊÔÃÕÜ][\w'-]+` precedido por `disse`, `respondeu`, `perguntou`) → lookup em `character_profiles`
2. **Alias explícito** — regex sobre `descriptive_aliases` do CharacterProfile → match no texto
3. **Pronome** — parser de corefência (`ele`/`ela`) → lookup em `character_profiles` por gender
4. **Entity em foco** — `focus_entity` do Scene Graph → candidato primário
5. **Embedding** — fallback: `resolve_descriptive_aliases` com `paraphrase-multilingual-MiniLM-L12-v2` → top-k candidatos

Apenas o passo 5 usa embedding. Steps 0–4 são regex e parsing de microssegundos. Cada candidate tem:
- `speaker_id: str`
- `score: float` (0.0–1.0)
- `evidence: list[EvidenceEntry]` (tipada)

O embedding é **fallback**: só é chamado se steps 0–4 falharem em resolver um candidato. O cache de embedding é por `character_id` (não por capítulo).

#### Scenario: CandidateGenerator Step 0 detecta 1ª pessoa
- **WHEN** a unidade contém `Por que eu ia ceder o assento?`
- **THEN** o Step 0 retorna evidência `{"type": "FIRST_PERSON", "detail": "eu"}` marcando como diálogo implícito

#### Scenario: CandidateGenerator Step 0 não finge atribuição de personagem
- **WHEN** a unidade contém `Por que eu ia ceder o assento?`
- **THEN** o Step 0 marca como 1ª pessoa, mas **NÃO** atribui um speaker_id — o Turn Tracker resolve quem fala

### Requirement: Turn Tracker — atribuição determinística de diálogos por cena

O sistema SHALL incluir um módulo `TurnTracker` (`llm/turn_tracker.py`) que atribui speaker_id a units classificados como "dialogue" por código determinístico (sem LLM). O Turn Tracker opera **por cena** e mantém estado de alternância:

1. **Lista de personagens ativos**: a partir da cena (lista de `speaker_id`s conhecida via cast discovery + candidate_generator)
2. **Rotação**: cada unit "dialogue" é atribuído ao próximo personagem na lista de forma alternada (circular)
3. **Foco narrativo**: se o `SceneGraph.focus_entity` está presente, o primeiro turno de diálogo de um novo bloco é do foco; turnos seguintes alternam
4. **Fallback**: se 1 personagem ativo, todos os diálogos vão para esse personagem; se 0, diálogos vão para `narrator`

O Turn Tracker retorna uma lista de `TurnAttribution` por unit:
- `unit_index: int`
- `speaker_id: str`
- `confidence: float` (1.0 para "dialogue" claro, 0.7 para "ambiguous")
- `evidence: list[EvidenceEntry]` (ex: `{"type": "TURN_TRACKER", "detail": "rotation"}`)

**Regra crítica**: Units classificados como "dialogue" que passam pelo Turn Tracker **NÃO** devem ser enviados à LLM para attribution. Apenas units classificados como "ambiguous" são enviados.

#### Scenario: Turn Tracker alterna entre 2 personagens
- **WHEN** uma cena tem 6 units classificados como "dialogue" e 2 personagens ativos (A, B)
- **THEN** os turns são atribuídos: A, B, A, B, A, B

#### Scenario: Turn Tracker com foco narrativo
- **WHEN** `focus_entity` é C e 3 novos units "dialogue" aparecem após uma transição de cena
- **THEN** o primeiro turno vai para C (foco), os seguintes alternam (C, A, B, ...)

#### Scenario: Turn Tracker com 1 personagem ativo
- **WHEN** uma cena tem 5 units "dialogue" e apenas 1 personagem conhecido
- **THEN** todos os 5 units são atribuídos a esse personagem

#### Scenario: Turn Tracker evita envio à LLM
- **WHEN** uma cena tem 20 units e 15 são classificados como "dialogue"
- **THEN** apenas 5 units ("ambiguous"/"narration") são enviados à LLM; os 12 "dialogue" são atribuídos pelo Turn Tracker

### Requirement: Attribution híbrida — LLM apenas para disambiguação

O pipeline SHALL substituir o passo **Speaker Attribution** (`llm/attribution.py`) por um fluxo híbrido:

1. **Fase determinística (80%+ dos units)**: Unit Classifier + CandidateGenerator + Turn Tracker atribuem a maioria dos units sem LLM
2. **Fase LLM (20%− units ambíguos)**: Apenas units classificados como "ambiguous" são enviados à LLM
3. **Contexto LLM**: O prompt de attribution contém **contexto completo da cena** (todos os units, personagens com perfis, atribuições já resolvidas, padrões de alternância)

O output da Attribution para units ambíguos deve incluir:
- `primary: str` — `speaker_id` do candidato principal
- `ranked_candidates: list[str]` — lista ordenada de ids
- `evidence: list[EvidenceEntry]` — lista de objetos com `type` explícito e `detail`
- `reason: str` — texto livre curto explicando a escolha

**Regra crítica**: Units "narration" classificados corretamente **NÃO** devem ser enviados à LLM. Units "dialogue" classificados pelo Turn Tracker **NÃO** devem ser enviados à LLM.

#### Scenario: Attribution processa units em lote
- **WHEN** uma cena tem 20 units
- **THEN** 12+ units são resolvidos por código (Turn Tracker), apenas 2–4 units ambíguos vão para LLM

#### Scenario: Attribution mantém unidades já resolvidas
- **WHEN** 15 units já foram atribuídos por Turn Tracker e 5 vão para LLM
- **THEN** o output final contém 20 atribuições (15 do Turn Tracker + 5 da LLM)

#### Scenario: Attribution com contexto de cena
- **WHEN** a LLM recebe units ambíguos
- **THEN** o user payload contém todos os units da cena, personagens com perfis, e atribuições já resolvidas

### Requirement: QA por cena (não por unit)

O sistema SHALL operar o Speaker QA **por cena**, não por unit individual. O QA avalia a consistência da cena inteira:

- **Narrator-collapse detection**: Se > `collapse_threshold` (default: 0.7) dos units "dialogue" foram atribuídos como `narrator`, a cena falha com severity RIGOROUS
- **Alternância verificada**: Se 2+ personagens ativos na cena, mas apenas 1 foi usado em units "dialogue", a cena falha
- **Closed-set**: Todos os speakers atribuídos (incluindo Turn Tracker) devem estar no allowed set
- **Speech-tag**: Units atribuídos por Turn Tracker não passam por verificação de speech-tag (não passaram por LLM)

Quando uma cena falha no QA por cena:
1. Os units ambíguos são reenviados à LLM com contexto do erro
2. O Turn Tracker é reexecutado com candidatos ajustados
3. Retry até `QA_CORRECTION_MAX_ATTEMPTS` (default: 3)
4. Se todas as tentativas falham: units ambíguos recebem `status: "needs_review"`

#### Scenario: QA por cena detecta narrator collapse
- **WHEN** uma cena tem 10 units "dialogue" e todos foram atribuídos como `narrator`
- **THEN** o QA de cena falha com severity RIGOROUS, triggerando retry

#### Scenario: QA por cena verifica alternância
- **WHEN** uma cena tem 3 personagens ativos mas apenas 1 aparece em units "dialogue"
- **THEN** o QA de cena falha se o texto indica múltiplos falantes

### Requirement: Caches — chave por cena, versionada (sem mudança)

O sistema SHALL manter dois caches independentes com chaves keyed por **cena** (não por capítulo):

**Attribution cache key:**
```
scene_hash + character_profile_hash + candidate_generator_version + attribution_policy_version
```

**Interpretation cache key:**
```
scene_hash + attribution_cache_key + prompt_version + adaptation_policy_version
```

Cada cache tem sua própria versão de política. Bump de versão em qualquer um dos caches invalida automaticamente os entries daquele cache específico.

O `candidate_generator_version` SHALL incluir o Step 0 (1ª pessoa) na versão do cache key para invalidar caches antigos.

#### Scenario: Bump de versão de attribution invalida apenas attribution cache
- **WHEN** a política de attribution muda
- **THEN** caches de attribution são invalidados, caches de interpretação permanecem válidos

#### Scenario: Cache keyed por cena (não por capítulo)
- **WHEN** uma cena é processada
- **THEN** o attribution cache e interpretation cache são keyed por `scene_hash` (não `chapter_hash`)

### Requirement: Prompt de attribution é dedicado e minimalista (modificado)

O arquivo de prompt de attribution (`llm/prompts/attribution.md`) SHALL conter instruções focadas **exclusivamente** na disambiguação de units ambíguos. O prompt NÃO deve conter regras de diarização genéricas — a maioria dos units já foi resolvida por código.

O user payload da disambiguação contém:
- `scene_text`: texto completo da cena
- `units`: lista de units com classificação prévia (já atribuídos + ambíguos)
- `ambiguity_units`: apenas os units que precisam de disambiguação
- `speakers`: personagens da cena com perfis (aliases, gender, role)
- `turn_history`: sequência de atribuições já resolvidas (para contexto de alternância)

O prompt deve ser limitado a ~50 linhas.

#### Scenario: Prompt de attribution carrega sem erros
- **WHEN** o backend inicia com o novo pipeline
- **THEN** `llm/prompts/attribution.md` é carregado com sucesso

## ADDED Requirements

### Requirement: Unit Classifier — classificação 4 classes (não 3)

O sistema SHALL incluir um módulo `UnitClassifier` (`llm/unit_classifier.py`) que classifica cada unit em **4 classes** (não 3):

1. **`narration`**: prosa pura, descrição de cena, 3ª pessoa, interior monologue
2. **`explicit_dialogue`**: aspas, travessão, atribuição explícita (disse, perguntou), **OU** marcadores de 1ª pessoa (`eu`, `meu`, `sou`, `por que eu`)
3. **`indirect_dialogue`**: discurso indireto (`Ele disse que...`)
4. **`ambiguous`**: não se encaixa em nenhuma das classes acima — requer disambiguação pela LLM

O Unit Classifier é implementado em `llm/unit_classifier.py`. Não depende da LLM. Retorna `UnitClassification` por unit.

#### Scenario: Unit Classifier retorna 4 classes
- **WHEN** uma cena com 20 units é processada
- **THEN** cada unit recebe uma classe: `narration`, `explicit_dialogue`, `indirect_dialogue`, ou `ambiguous`

#### Scenario: "Eu me perguntei" é classificado como explicit_dialogue
- **WHEN** a unidade contém `Eu me perguntei se ele estava bravo`
- **THEN** o unit é classificado como `explicit_dialogue` (marcador 1ª pessoa)

#### Scenario: "Ele sorriu" é classificado como narration
- **WHEN** a unidade contém `Ele sorriu amplamente e cruzou as pernas.`
- **THEN** o unit é classificado como `narration` (3ª pessoa)

#### Scenario: "Hã! Que raciocínio absurdo" é classificado como explicit_dialogue
- **WHEN** a unidade contém `Hã! Que raciocínio absurdo.`
- **THEN** o unit é classificado como `explicit_dialogue` (terminação em `!`)

#### Scenario: Unidade sem marcador vai para ambiguous
- **WHEN** a unidade contém `O garoto estava sentado na cadeira.`
- **THEN** o unit é classificado como `ambiguous` (3ª pessoa, sem aspas, sem marcador)

### Requirement: Pipeline de attribution híbrida no backend

O sistema SHALL integrar o Unit Classifier e Turn Tracker no pipeline de interpretação (em `llm/ollama_backend.py::interpret_chapter_v2`):

```
Phase 0: Scene Segmentation
Phase 1: Cast Discovery
Phase 2: Build CharacterProfiles
Phase 3: Unit Classification (NOVO) → 4 classes por unit
Phase 4: Build Scene Graph
Phase 5: Turn Tracking (NOVO) → atribuição determinística de units "dialogue"
Phase 6: CandidateGenerator → para units "ambiguous"
Phase 7: Attribution (LLM) → apenas units "ambiguous"
Phase 8: Scene-level QA
Phase 9: Interpretation per unit
```

O pipeline SHALL garantir que:
- Units "narration" → classificados como narrator, sem LLM
- Units "explicit_dialogue" → atribuídos por Turn Tracker, sem LLM (a menos que 0 candidatos)
- Units "ambiguous" → enviados à LLM com contexto completo

#### Scenario: Pipeline híbrido processa cena corretamente
- **WHEN** uma cena com 20 units é processada
- **THEN** ~70% dos units são resolvidos por código (Turn Tracker), ~30% pela LLM

#### Scenario: Pipeline sem unidades ambíguas evita LLM
- **WHEN** uma cena é 100% "dialogue" ou "narration"
- **THEN** nenhuma chamada LLM de attribution é feita para esta cena

### Requirement: Debug output por cena (estendido)

O sistema SHALL persistir debug output de cada cena em `out/<book_id>/chapters/<chapter_id>/debug_scene_<scene_id>.json` contendo:
- `unit_classifications`: classificação de cada unit pelo Unit Classifier
- `turn_tracking`: atribuições do Turn Tracker (unit_index → speaker_id)
- `llm_disambiguation`: units enviados à LLM e resultados
- `qa_results`: resultados do QA por cena
- `total_units`, `resolved_by_code`, `resolved_by_llm`, `needs_review`

#### Scenario: Debug output contém classificações
- **WHEN** uma cena é processada
- **THEN** `debug_scene_<id>.json` inclui `unit_classifications` com classe de cada unit

#### Scenario: Debug output contém métricas de resolução
- **WHEN** uma cena é processada
- **THEN** `debug_scene_<id>.json` inclui `total_units: 20`, `resolved_by_code: 14`, `resolved_by_llm: 6`
