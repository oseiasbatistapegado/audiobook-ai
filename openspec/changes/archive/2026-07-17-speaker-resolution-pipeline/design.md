## Context

O pipeline de interpretação de capítulos (`OllamaBackend.interpret_chapter`) envia o texto a uma única chamada LLM que deve simultaneamente: identificar personagens, resolver aliases, distinguir narração de fala, atribuir emoções, traduzir para pt-BR e gerar JSON válido. O modelo `qwen3:8b` falha nesses invariantes, gerando rejeição no QA e retries encadeados que consomem GPU.

O problema é **conceitual**: o pipeline trata a interpretação como um **pipeline de prompts**, quando na verdade é um **pipeline de compilação**. Cada etapa LLM faz três coisas cognitivamente distintas (extrair estrutura, tomar decisão, gerar texto), e o 8B não é calibrado para nenhuma delas com confiabilidade.

## Goals / Non-Goals

**Goals:**
- Tratar a interpretação como compilação NL: 6 etapas LLM (extrair/adaptar) + 4 etapas determinísticas (estruturar/resolver/validar)
- Separar CharacterProfile (imutável, cross-capítulo) de SceneProfile (temporal por cena)
- Mover relações interpersonais para InteractionGraph (dados da cena, não do personagem)
- CandidateGenerator 100% determinístico (regex → parser → embedding como último recurso)
- Evidence tipada como **input do QA**, não apenas debug
- Interpretation reduzida ao mínimo: `speaker_id` + `emotion constraints` + `adaptation policy`
- `InterpretationState` como objeto único de estado (AST-like)
- Caches separados de attribution e interpretação

**Non-Goals:**
- Mudar o modelo base (continua `qwen3:8b` para interpretação)
- Paralelizar processamento de capítulos (futuro)
- Alterar o sistema de resume/checkpoint (manifest.json)
- Substituir o sistema de merge de áudio

## Architecture: Pipeline de Compilação NL

```
Raw Text (capítulo)
        │
        ▼
┌─────────────────────────┐
│ 0. Scene Segmentation   │  ← Código determinístico
│  (scene_segmenter.py)   │  Divide capítulo em cenas (8–20 segmentos)
└────────┬────────────────┘
         │ list[Scene]
         │
         ▼
┌─────────────────────────┐
│ 1. Cast Discovery       │  ← LLM (qwen3:8b)
│  (ollama_backend.py)    │  Descobre personagens: id, name, aliases, participation
│                         │  NÃO inventa conhecimento persistente
└────────┬────────────────┘
         │ list[Character]
         │
         ▼
┌─────────────────────────┐
│ 2. CharacterProfiles    │  ← Código + cache persistente
│  (profile_manager.py)   │  Perfis imutáveis: aliases, gender, role, known_names
│                         │  Cache por character_id (não por capítulo)
└────────┬────────────────┘
         │ character_profiles + list[Character]
         │
         ▼
┌─────────────────────────┐
│ 3. Scene Graph Builder  │  ← Código determinístico
│  (scene_graph.py)       │  Constrói grafo narrativo por cena:
│                         │    entities, actions, dialogue edges, references, focus
└────────┬────────────────┘
         │ scene_graph per scene
         │
         ▼
┌─────────────────────────┐
│ 4. Candidate Generator  │  ← Código determinístico (regex → parser → embed fallback)
│  (candidate_generator.py) │ Pipeline de resolução:
│                         │    1. Nome explícito no texto
│                         │    2. Alias explícito (regex sobre character profiles)
│                         │    3. Pronome (parser de corefência)
│                         │    4. Entity em foco (scene graph)
│                         │    5. Embedding (fallback, cache por personagem)
└────────┬────────────────┘
         │ candidates por segmento
         │
         ▼
┌─────────────────────────┐
│ 5. Speaker Attribution  │  ← LLM (qwen3:8b)
│  (attribution.py)       │  Escolhe entre candidatos já preparados.
│                         │  Retorna: primary, ranked_candidates, evidence tipada
│                         │  NÃO traduz, NÃO formata emoções, NÃO gera JSON final
└────────┬────────────────┘
         │ attributions + evidence tipada
         │
         ▼
┌─────────────────────────┐
│ 6. QA Local             │  ← Código determinístico
│  (speaker_qa.py)        │  QA consome evidence:
│                         │    EXPLICIT → passa sem validação adicional
│                         │    TURN_ORDER → verifica alternância de speakers
│                         │    EMBEDDING → rigoroso se gap ≤ 0.20
│                         │  Se falha: retry local → status: "needs_review"
└────────┬────────────────┘
         │ units validadas
         │
         ▼
┌─────────────────────────┐
│ 7. Interpretation       │  ← LLM (qwen3:8b)
│  (ollama_backend.py)    │  Formata com emoção, estilo, pt-BR.
│                         │  Input mínimo: speaker_id + emotion constraints
│                         │  + adaptation policy. Nada mais.
└────────┬────────────────┘
         │ LLMChapterResponse
         │
         ▼
┌─────────────────────────┐
│ 8. Validation           │  ← Código (Pydantic + QA final)
│  (ollama_backend.py)    │  Validação Pydantic + invariantes finais.
│                         │  Caches: attribution (separado) + interpretation (separado)
└────────┬────────────────┘
         │ units finais
         │
         ▼
┌─────────────────────────┐
│ 9. TTS                  │  ← Worker subprocesso
│  (gpu/orchestrate.py)   │  Omite status: "needs_review" do merge.
└─────────────────────────┘
```

## Estado Central: InterpretationState

Cada etapa do pipeline recebe e retorna o mesmo objeto `InterpretationState`, que acumula estado de forma idempotente — similar a um AST em compiladores. Cada etapa modifica apenas a parte que lhe compete:

```python
class InterpretationState:
    # Fase 0: Scene Segmentation
    scenes: list[Scene]                    # Cenas divididas

    # Fase 1: Cast Discovery
    characters: list[Character]            # Personagens do capítulo
    character_profiles: dict[str, CharacterProfile]  # Perfis imutáveis

    # Fase 3: Scene Graph (por cena)
    scene_graphs: dict[str, SceneGraph]    # scene_id → grafo

    # Fase 4: Candidate Generator (por cena)
    candidates: dict[str, list[Candidate]] # scene_id → candidatos

    # Fase 5: Attribution (por cena)
    attributions: dict[str, list[DialogueAttribution]]  # scene_id → atribuições

    # Fase 6: QA Local
    qa_status: dict[str, list[str]]        # scene_id → [status per unit]
    rejected_units: set[tuple[str, int]]   # (scene, unit) com status: "needs_review"

    # Fase 7: Interpretation
    interpretations: dict[str, list[Dialogue]]  # scene_id → diálogos interpretados
```

**Propriedades:**
- **Imutabilidade por fase:** cada fase adiciona dados ao state, não modifica dados anteriores
- **Isolamento:** cada cena é um "módulo compilado" independente — attribution de cena 7 não depende do state da cena 3
- **Cache por cena:** cache de attribution e interpretação é keyed por `scene_hash`, não por capítulo inteiro
- **Debug:** o state é serializável em cada fase para debugging (ex: dump do state após Scene Graph Builder)

## Decisions

### D1: Scene Segmentation como primeira etapa

**Decisão:** Antes de qualquer processamento, o texto é dividido em cenas por código determinístico (`llm/scene_segmenter.py`). Cenas são identificadas por: mudança de foco narrativo, entrada/saída de personagens, quebra de diálogo, mudança de tempo/lugar. Cada cena tem tipicamente 8–20 segmentos.

**Racional:** Processar cena por cena (não capítulo) reduz o contexto que cada etapa precisa lidar e evita o problema de batching adaptativo (o que era ambíguo antes). Cena é a unidade natural de processamento narrativo.

### D2: CharacterProfile imutável vs SceneProfile temporal

**Decisão:** `CharacterProfile` contém **fatos imutáveis** sobre um personagem: `id`, `name`, `aliases`, `gender`, `role` (POV/secondary/teacher/etc.), `known_names`. É persistente e compartilhado entre capítulos.

`SceneProfile` contém **inferências temporais** sobre um personagem num capítulo/cena específica: `mood` (está irritada, está calma), `speech_patterns` (fala curta, evita contato visual), `interactions` (está conversando com Ayanokoji). É descartado ao final da cena.

**Racional:** "Fala formal" é um fato persistente (CharacterProfile). "Está irritada neste capítulo" é uma inferência temporária (SceneProfile). Misturar os dois causa inconsistência cross-capítulo: a LLM pode retornar "fala agressiva" num capítulo e "fala formal" no outro.

### D3: InteractionGraph substitui relationships

**Decisão:** Relações interpersonais não são mais campos do `CharacterProfile`. Elas são construídas como um **InteractionGraph** (`llm/scene_graph.py`) por cena:

```python
class InteractionGraph:
    entities: list[EntityNode]           # personagens na cena
    edges: list[InteractionEdge]         # relações direcionadas
    focus_entity: str | None             # quem está em foco
```

Cada `InteractionEdge` tem: `source`, `target`, `type` (responde/interrup/olha/interrompe), `scene_id`.

**Racional:** Relações são **dados da cena**, não do personagem. Sudou interrompe Hirata num capítulo, mas não no próximo. Armazenar relações no perfil do personagem é uma inferência que quebra consistência.

### D4: CandidateGenerator totalmente determinístico

**Decisão:** `CandidateGenerator` (`llm/candidate_generator.py`) é 100% código — sem LLM. Pipeline em cascata:

1. **Nome explícito** — regex no texto (`[A-ZÁÉÍÓÚÂÊÔÃÕÜ][\w'-]+` precedido por `disse`, `respondeu`, `perguntou`) → lookup em `character_profiles`
2. **Alias explícito** — regex sobre `descriptive_aliases` do CharacterProfile → match no texto
3. **Pronome** — parser de corefência (`ele`/`ela` → lookup em `character_profiles` por gender) → match no texto
4. **Entity em foco** — `focus_entity` do Scene Graph → candidato primário
5. **Embedding** — fallback: `resolve_descriptive_aliases` com `paraphrase-multilingual-MiniLM-L12-v2` → top-k candidatos

Apenas o passo 5 usa embedding. Steps 1–4 são regex e parsing de microssegundos.

**Racional:** Modelos LLM não são calibrados — `confidence: 0.87` não significa 87% de chance. O gap de embedding é objetivo; a confidence da LLM é apenas mais uma saída generativa. Regex custa microssegundos; embedding é caro.

### D5: Evidence como input do QA

**Decisão:** A evidence tipada deixa de ser apenas debug e vira **entrada do QA**:

```
EXPLICIT → QA skip (passa sem validação adicional)
TURN_ORDER → QA verifica alternância de speakers
SCENE_CONTEXT → QA moderado
ALIAS_MATCH → QA moderado
EMBEDDING → QA rigoroso se gap ≤ 0.20
RELATIONSHIP → QA moderado
```

O QA consome `evidence.type` para decidir o rigor de validação, não apenas o gap de embedding.

**Racional:** Se a evidence é `EXPLICIT` (disse Horikita), não precisa validar. Se é `EMBEDDING` (gap 0.91 vs 0.88), o QA deve ser rigoroso. Evidence como input torna o QA inteligente, não apenas reativo.

### D6: QA por unidade isolada com `status: "needs_review"`

**Decisão:** Cada unidade tem seu próprio ciclo de retry. Se todas as tentativas esgotadas:
- `status: "needs_review"`, `speaker_id: null`, `text: original_text`, `emotion: "neutral"`
- **NÃO** `speaker="narrator"` e **NÃO** `text="[REJECT]"`
- O downstream TTS omite o segmento do merge
- `rejection_reason` é derivado da `evidence` (ex: "gap embedding 0.03")

**Racional:** `needs_review` comunica semanticamente que o segmento existe, só não sabemos quem fala. `rejected` soa como erro fatal. O downstream TTS filtra por `status != null`.

### D7: Interpretation simplificada ao mínimo

**Decisão:** A Interpretation Pass recebe no user payload **apenas**:
- `speaker_id` (já resolvido)
- `emotion constraints` (enum fechado: neutral/happy/sad/angry/fear/excited/whisper)
- `adaptation policy` (version hash, regras de pt-BR)

**NÃO recebe:** perfis de personagens, scene graph, conversation state, aliases, relationships, speaking style, role, contextual info. Tudo isso já foi resolvido.

**Racional:** Quanto menor o prompt da LLM na geração, menor a variabilidade. A LLM na interpretação não precisa decidir "quem fala" — já sabe. Só precisa formatar com emoção e adaptar para pt-BR.

### D8: InterpretationState como objeto único de estado

**Decisão:** O `InterpretationState` (`llm/interpretation_state.py`) é o objeto central compartilhado entre todas as etapas do pipeline. Cada etapa adiciona dados ao state sem modificar dados anteriores — similar a um AST em compiladores.

**Racional:** 6 objetos de estado espalhados (`SceneTracker`, `resolved_context`, `candidates`, `attribution`, `qa_status`, `interpretations`) acabam acoplados e difíceis de gerenciar. Um único state com campos isolados por fase é mais previsível, mais debuggable, e mais fácil de versionar por cache.

### D9: Caches separados de attribution e interpretação

**Decisão:** Dois caches independentes:

**Attribution cache key:**
```
scene_hash + character_profile_hash + candidate_generator_version + attribution_policy_version
```

**Interpretation cache key:**
```
scene_hash + attribution_cache_key + prompt_version + adaptation_policy_version
```

**Racional:** Você pode melhorar a tradução/estilo (mudança de prompt de interpretação) sem recalculatr attribution. Caches independentes = invalidação granular por cena (não por capítulo).

## Risks / Trade-offs

| Risk | Impacto | Mitigação |
|------|---------|-----------|
| Scene Graph adiciona complexidade ao pipeline | Médio | Implementado como código puro (sem LLM). Estado isolado no InterpretationState. |
| CandidateGenerator sem embedding em capítulos novos = menos precisão | Médio | Steps 1–4 cobrem ~80% dos casos (nomes explícitos, aliases, pronomes). Embedding só entra quando necessário. |
| Scene Segmentation por código pode dividir cenas incorretamente | Alto | Heurística baseada em mudanças de foco (mais confiável que divisão por parágrafo). Testes de regressão cobrem casos comuns. |
| CharacterProfile imutável vs SceneProfile temporal = mais modelos | Baixo | Ambos em `models/cast.py`. ProfileManager gerencia a distinção. |
| InterpretationState grande = serialização cara | Baixo | State é serializado **por cena**, não por capítulo. Cada cena é um "compilation unit" independente. |
| Evidence como input do QA = mais complexidade no QA | Médio | Mapeamento `evidence.type → severity` é uma tabela simples. QA já tem 6 invariantes. |

## Migration Plan

1. **Fase 1:** Criar `InterpretationState` como objeto único de estado. Adicionar `CharacterProfile` (imutável) + `SceneProfile` (temporal). Manter backward compat.
2. **Fase 2:** Criar `scene_segmenter.py` + `scene_graph.py` (Scene Graph Builder). Criar `candidate_generator.py` (determinístico).
3. **Fase 3:** Criar `attribution.py` com evidence tipada. Modificar `speaker_qa.py` para consumir evidence. Criar `attribution.md`.
4. **Fase 4:** Modificar Interpretation para input mínimo (speaker_id + emotion + adaptation policy). QA por unidade com `status: "needs_review"`.
5. **Fase 5:** Adicionar embeddings com `paraphrase-multilingual-MiniLM-L12-v2`, cache por personagem (opcional, flag).
6. **Fase 6:** Separar caches de attribution e interpretação por cena. Bump versões de fingerprint.

Cada fase é reversível via flag `SPEAKER_RESOLUTION_V2_ENABLED`. Rollback: desabilitar flag restaura o pipeline antigo.

## Open Questions

1. **Heurística de Scene Segmentation:** Deve ser baseada em mudanças de foco + quebra de diálogo + entrada/saída de personagens? Ou usar uma LLM mais leve? Heurística de código é preferível (0ms, determinístico).
2. **Limiar de gap de embedding:** O limiar de `0.20` para gap entre scores é arbitrário. Pode ser calibrado com dados reais.
3. **TTL de CharacterProfile:** Perfiles imutáveis persistem cross-capítulo. Quando recalcular? Só quando cast discovery retorna um novo character_id.
