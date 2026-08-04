## Purpose

Tratar a interpretação de capítulos como **compilação de linguagem natural**: etapas determinísticas extraem estrutura; etapas LLM apenas adaptam. O pipeline divide-se em 10 etapas (6 LLM + 4 código), com `InterpretationState` como objeto único de estado (AST-like).

## Requirements

### Requirement: Scene Segmentation divide capítulo em cenas

O sistema SHALL incluir um módulo `SceneSegmenter` (`llm/scene_segmenter.py`) que recebe o texto cru do capítulo e retorna uma lista de `Scene` com tipicamente 8–20 segmentos cada. A segmentação é **totalmente determinística** (código, sem LLM), baseada em:

- Mudança de foco narrativo (novo personagem em cena)
- Entrada/saída de personagens (`entrou`, `saiu`, `deixou`)
- Quebra de diálogo (nova linha com novo speaker não listado)
- Mudança de tempo/lugar (indicadores temporais/espaciais)

Cada `Scene` tem: `scene_id` (sequencial), `units` (lista de unidades de texto), `text` (texto completo da cena).

#### Scenario: Scene Segmentation processa capítulo em cenas
- **WHEN** um capítulo com 120 segmentos é segmentado
- **THEN** são geradas ~8 cenas de ~15 segmentos cada

#### Scenario: Scene Segmentation é determinística
- **WHEN** o mesmo texto de capítulo é segmentado duas vezes
- **THEN** o resultado é idêntico (mesma divisão em cenas)

### Requirement: Cast Discovery retorna apenas personagens e ids

O Pass 1 (cast discovery) SHALL retornar apenas personagens com `id`, `name`, `aliases` e `participation`. **NÃO** deve enriquecer perfis com inferências persistentes (`descriptive_aliases`, `speech_traits`, `relationships`, `speaking_style`, `role`). O Cast Discovery é uma etapa LLM mínima: apenas descobrir quem aparece no capítulo.

#### Scenario: Cast Discovery retorna ids e participação
- **WHEN** o Pass 1 analisa o capítulo
- **THEN** retorna personagens com `id`, `name`, `aliases`, `participation` (sem `speaker_profile`)

#### Scenario: Cast Discovery sem inferências persistidas
- **WHEN** o texto contém "Horikita é fria" (inferência sobre personalidade)
- **THEN** o Cast Discovery **não** armazena "fria" como trait persistente do personagem

### Requirement: CharacterProfile imutável vs SceneProfile temporal

O sistema SHALL distinguir dois tipos de perfil de personagem:

**CharacterProfile** (imutável, cross-capítulo):
- `id`, `name`, `aliases` (slugs canônicos), `gender`, `role` (POV/secondary/teacher/etc.), `known_names` (todos os nomes pelos quais o personagem é identificado no texto)

**SceneProfile** (temporal por cena):
- `mood` (está irritada, está calma), `speech_patterns` (fala curta, evita contato visual), `interactions` (está conversando com X), `active_actions` (entrou, sentou, sorriu)

O `CharacterProfile` é cacheado por `character_id` (não por capítulo). O `SceneProfile` é descartado ao final da cena.

#### Scenario: CharacterProfile é persistente
- **WHEN** Horikita é processada no capítulo 1 com `role: "secondary"`
- **THEN** no capítulo 2, o `CharacterProfile` de Horikita mantém `role: "secondary"` (não é recalculado)

#### Scenario: SceneProfile é descartado após cena
- **WHEN** uma cena termina
- **THEN** o `SceneProfile` desta cena é descartado (não persiste para a próxima cena)

### Requirement: Scene Graph modela interações por cena

O sistema SHALL incluir um módulo `SceneGraph` (`llm/scene_graph.py`) que modela a estrutura narrativa de cada cena:

```python
class SceneGraph:
    entities: list[EntityNode]       # personagens na cena
    edges: list[InteractionEdge]     # relações direcionadas (responde, interrompe, olha)
    focus_entity: str | None         # personagem em foco narrativo
    turn_order: list[dict]           # sequência de falas (unit_index, speaker, type)
    entity_actions: list[dict]       # ações descritas (entity, action, unit_index)
```

O `SceneGraph` é construído por código determinístico (`scene_graph_builder.py`), **não pela LLM**. Ele é alimentado pelo classificador 3 classes (`llm/sanitizer.py`) e pelo texto original.

**InteractionEdge** substitui `relationships` no `CharacterProfile`:
- `source: str` (character_id)
- `target: str | None` (character_id — pode ser null para ações não-direcionadas)
- `type: str` (responde/interrup/olha/fala_com/interrompe/…)
- `scene_id: str` (cena à qual a interação pertence)

#### Scenario: Scene Graph identifica personagens em cena
- **WHEN** uma cena contém "Horikita entrou. Ela sentou."
- **THEN** o `entities` inclui `horikita_suzune` e `focus_entity` é `horikita_suzune`

#### Scenario: Scene Graph vincula ação a entidade
- **WHEN** uma cena contém "Sorriu. — Tudo bem."
- **THEN** o `entity_actions` inclui `{"entity": "horikita_suzune", "action": "sorriu"}`

#### Scenario: Scene Graph contém interação entre personagens
- **WHEN** uma cena contém "— Você está atrasado, disse Horikita a Ayanokoji."
- **THEN** o `edges` inclui `InteractionEdge(source="horikita_suzune", target="ayanokoji_kiyotaka", type="responde")`

### Requirement: Classificação 3 classes de segmento

O sistema SHALL classificar cada segmento como `explicit_dialogue`, `indirect_dialogue`, ou `narration` por código determinístico (não pela LLM). O classificador categoriza:

- **EXPLICIT_DIALOGUE**: texto entre aspas (`"`, `""`), travessão (`—`, `–`), ou contendo atribuição explícita (disse, perguntou, respondeu, gritou, sussurrou)
- **INDIRECT_DIALOGUE**: discurso indireto ("Ele disse que iria embora.") — marcado com flag `is_indirect=true`
- **NARRATION**: prosa pura, descrição de cena, interior monologue

O classificador é implementado em `llm/sanitizer.py`. Não depende da LLM.

#### Scenario: Aspas são classificadas como explicit_dialogue
- **WHEN** a unidade contém `"Você está atrasado."`
- **THEN** o segmento é classificado como `explicit_dialogue`

#### Scenario: Travessão é classificado como explicit_dialogue
- **WHEN** a unidade contém `— Você está atrasado.`
- **THEN** o segmento é classificado como `explicit_dialogue`

#### Scenario: Discurso indireto é classificado como indirect_dialogue
- **WHEN** a unidade contém `Ele disse que não ia mais.`
- **THEN** o segmento é classificado como `indirect_dialogue` com `is_indirect=true`

#### Scenario: Prosa pura é classificada como narration
- **WHEN** a unidade contém `Eu estava cansado naquele dia.` sem aspas
- **THEN** o segmento é classificado como `narration`

### Requirement: CandidateGenerator totalmente determinístico

O sistema SHALL incluir um módulo `CandidateGenerator` (`llm/candidate_generator.py`) que produz candidatos de speaker para cada segmento, **totalmente por código** (sem LLM). Pipeline em cascata:

1. **Nome explícito** — regex no texto (`[A-ZÁÉÍÓÚÂÊÔÃÕÜ][\w'-]+` precedido por `disse`, `respondeu`, `perguntou`) → lookup em `character_profiles`
2. **Alias explícito** — regex sobre `descriptive_aliases` do CharacterProfile → match no texto
3. **Pronome** — parser de corefência (`ele`/`ela`) → lookup em `character_profiles` por gender
4. **Entity em foco** — `focus_entity` do Scene Graph → candidato primário
5. **Embedding** — fallback: `resolve_descriptive_aliases` com `paraphrase-multilingual-MiniLM-L12-v2` → top-k candidatos

Apenas o passo 5 usa embedding. Steps 1–4 são regex e parsing de microssegundos. Cada candidate tem:
- `speaker_id: str`
- `score: float` (0.0–1.0)
- `evidence: list[EvidenceEntry]` (tipada)

O embedding é **fallback**: só é chamado se steps 1–4 falharem em resolver um candidato. O cache de embedding é por `character_id` (não por capítulo).

#### Scenario: CandidateGenerator resolve por nome explícito
- **WHEN** o texto contém `"Prova?", disse Horikita.`
- **THEN** o step 1 retorna `horikita_suzune` com score alto (match direto no character profile)

#### Scenario: CandidateGenerator usa embedding como fallback
- **WHEN** o texto contém `O garoto de cabelos negros sorriu.` (sem nome explícito)
- **THEN** steps 1–4 falham; o step 5 (embedding) é chamado como fallback

#### Scenario: Embedding cache por personagem
- **WHEN** Horikita foi embedada no capítulo 1
- **THEN** no capítulo 2, o embedding de Horikita é reutilizado (cache hit)

### Requirement: Attribution por cena com evidence tipada

O pipeline SHALL incluir um passo **Speaker Attribution** (`llm/attribution.py`) que recebe unidades agrupadas por cena, os candidatos do `CandidateGenerator`, e retorna um mapeamento de `speaker_id` para cada segmento. A Attribution **NÃO** traduz, **NÃO** formata emoções, **NÃO** gera JSON final — apenas classifica o autor.

O output da Attribution para cada segmento deve incluir:
- `primary: str` — `speaker_id` do candidato principal
- `ranked_candidates: list[str]` — lista ordenada de ids
- `evidence: list[EvidenceEntry]` — lista de objetos com `type` explícito e `detail`
- `reason: str` — texto livre curto explicando a escolha

Tipos de evidence:
- **EXPLICIT** — atribuição explícita no texto (disse, perguntou, respondeu + nome)
- **TURN_ORDER** — inferido pela ordem dos falantes (precedido por X)
- **SCENE_CONTEXT** — inferido pelo Scene Graph (entidade em foco)
- **ALIAS_MATCH** — alias descritivo no texto corresponde a um perfil
- **EMBEDDING** — similaridade semântica de embedding (gap de cosine similarity)
- **RELATIONSHIP** — relação interpersonacional resolve ambiguidade

O batching da Attribution é por **cena** (não por capítulo nem bloco fixo). Cada cena tem tipicamente 8–20 segmentos.

#### Scenario: Attribution com atribuição explícita
- **WHEN** a unidade contém `"Prova?", perguntou Horikita.`
- **THEN** o attribution retorna `primary: "horikita_suzune"`, evidence contendo `EXPLICIT`

#### Scenario: Attribution com diálogo encadeado
- **WHEN** unidades consecutivas têm diálogos sem atribuição explícita ("Você veio." / "Sim.")
- **THEN** o attribution usa `turn_order` do Scene Graph para resolver corretamente

#### Scenario: Attribution com batching por cena
- **WHEN** um capítulo tem 120 segmentos de texto (8 cenas)
- **THEN** o attribution processa 8 chamadas LLM (uma por cena), não 6 chamadas de 20 unidades

#### Scenario: Attribution com evidence tipada
- **WHEN** a unidade é resolvida por múltiplas evidências
- **THEN** o attribution retorna `evidence` contendo `EXPLICIT` (disse X) + `TURN_ORDER` (precedido por Y)

### Requirement: QA consome evidence como input

O QA SHALL operar por unidade individual e consumir `evidence.type` para decidir o **rigor de validação**:

| evidence.type | Rigor do QA |
|---|---|
| `EXPLICIT` | Skip (passa sem validação adicional) |
| `TURN_ORDER` | Moderado (verifica alternância de speakers) |
| `SCENE_CONTEXT` | Moderado |
| `ALIAS_MATCH` | Moderado |
| `EMBEDDING` | Rigoroso se gap ≤ `ATTRIBUTION_EMBEDDING_GAP_THRESHOLD` (default: `0.20`) |
| `RELATIONSHIP` | Moderado |

Quando uma unidade falha no QA:
1. O erro é injetado no prompt de retry para aquela unidade específica
2. A unidade é reprocessada em loop até `QA_CORRECTION_MAX_ATTEMPTS` (default: 3)
3. Se todas as tentativas falham: `status: "needs_review"`, `speaker_id: null`, `text: original_text`, `emotion: "neutral"`, `rejection_reason: "..."`
4. O capítulo continua processando as demais unidades
5. O downstream (TTS phase) detecta `status: "needs_review"` e **omite** o segmento do áudio

**Racional:** Se a evidence é `EXPLICIT` (disse Horikita), não precisa validar. Se é `EMBEDDING` (gap 0.91 vs 0.88), o QA deve ser rigoroso. Evidence como input torna o QA inteligente, não apenas reativo.

#### Scenario: Evidence EXPLICIT passa sem validação adicional
- **WHEN** a unidade tem evidence contendo `{"type": "EXPLICIT", "detail": "disse Horikita"}`
- **THEN** o QA **não** aplica invariantes adicionais (passa direto)

#### Scenario: Evidence TURN_ORDER aciona QA moderado
- **WHEN** a unidade tem evidence `{"type": "TURN_ORDER", "detail": "precedido por ayanokoji"}`
- **THEN** o QA verifica alternância de speakers (se o speaker anterior foi ayanokoji, o QA é rigoroso)

#### Scenario: Evidence EMBEDDING com gap pequeno aciona QA rigoroso
- **WHEN** a unidade tem evidence `{"type": "EMBEDDING", "detail": "gap=0.03"}` (≤ 0.20)
- **THEN** o QA aplica todos os invariantes sem atenuantes

#### Scenario: Unidade que falha 3x recebe status: needs_review
- **WHEN** a unidade 54 falha 3 tentativas consecutivas no QA
- **THEN** a unidade é mantida com `{status: "needs_review", speaker_id: null, text: original, emotion: "neutral"}`
- **THEN** o downstream TTS omite este segmento do áudio final

#### Scenario: Unidade needs_review é omitida pelo downstream TTS
- **WHEN** uma unidade tem `status: "needs_review"`
- **THEN** o TTS phase **não** gera áudio para este segmento (omitido do merge)

### Requirement: Caches separados de attribution e interpretação

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

#### Scenario: Bump de versão de attribution invalida apenas attribution cache
- **WHEN** a política de attribution muda
- **THEN** caches de attribution são invalidados, caches de interpretação permanecem válidos

#### Scenario: Bump de versão de interpretação invalida apenas interpretação cache
- **WHEN** o prompt de interpretação muda (estilo/emoção)
- **THEN** caches de interpretação são invalidados, caches de attribution permanecem válidos

#### Scenario: Cache keyed por cena (não por capítulo)
- **WHEN** uma cena é processada
- **THEN** o attribution cache e interpretation cache são keyed por `scene_hash` (não `chapter_hash`)

### Requirement: Prompt de attribution é dedicado e minimalista

O arquivo de prompt de attribution (`llm/prompts/attribution.md`) SHALL conter instruções focadas exclusivamente na classificação de falantes, sem misturar regras de tradução, estilo, emoção ou formatação JSON. O prompt deve ser limitado a ~40 linhas. O prompt instrui o modelo a retornar: `primary` (speaker_id), `ranked_candidates` (lista ordenada), `evidence` (lista de `{type, detail}`), `reason` (texto livre curto).

#### Scenario: Prompt de attribution carrega sem erros
- **WHEN** o backend inicia com o novo pipeline
- **THEN** `llm/prompts/attribution.md` é carregado com sucesso

#### Scenario: Prompt de attribution é mais curto que interpret_chapter
- **WHEN** ambos os prompts são comparados
- **THEN** `attribution.md` tem menos linhas que `interpret_chapter.md`

### Requirement: Prompt de interpretação é simplificado ao mínimo

O arquivo de prompt de interpretação (`llm/prompts/interpret_chapter.md`) SHALL conter instruções focadas **exclusivamente** na formatação com emoção, estilo e pt-BR. **NÃO** deve conter regras de diarização — tudo isso já foi resolvido pela Attribution Pass. O prompt deve instruir a LLM a usar o `speaker_id` fornecido no user payload, não inventar novos.

O user payload da Interpretação contém **apenas**:
- `speaker_id` (já resolvido)
- `emotion_constraints` (enum fechado)
- `adaptation_policy` (version hash, regras de pt-BR)
- `unit_text` (texto da unidade)

**NÃO contém:** perfis de personagens, scene graph, conversation state, aliases, relationships, speaking style, role, contextual info.

#### Scenario: Prompt de interpretação não contém regras de diarização
- **WHEN** `interpret_chapter.md` é avaliado
- **THEN** não há instruções sobre "escolher speaker", "prosa → narrator", "speaker set fechado" — tudo isso já foi resolvido

#### Scenario: Prompt de interpretação é mais curto que attribution
- **WHEN** `interpret_chapter.md` é comparado a `attribution.md`
- **THEN** `interpret_chapter.md` é equivalente ou menor em linhas (sem regras de diarização redundantes)
