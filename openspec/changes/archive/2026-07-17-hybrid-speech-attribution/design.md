## Context

O pipeline atual de speaker attribution (v2) opera **unit-by-unit** ou **scene-by-scene com LLM pura**: cada unidade de texto é enviada para a LLM em uma chamada de attribution, e a LLM decide o speaker de cada unit isoladamente. Em textos de romance japonês traduzido, 60–80% dos units são diálogos sem marcação explícita (`disse X`) — sem aspas, sem travessão, sem atribuição de falante. A LLM, vendo units isolados, colapsa para `narrator` porque não tem contexto de conversação.

O problema não é a capacidade do modelo (qwen3.6-35B-a3b-mtp é poderoso), mas o **padrão de uso**: units isolados sem contexto de alternância, sem marcadores de 1ª pessoa, e com fallback silencioso para narrator.

Arquitetura atual (simplificada):

```
Chapter Text
    │
    ▼
Scene Segmentation → Scenes (8–20 units each)
    │
    ▼
Cast Discovery (LLM) → character list
    │
    ▼
CandidateGenerator (per unit, code) → candidates per unit
    │
    ▼
Attribution (per scene, LLM) → speaker_id per unit ← PROBLEMA AQUI
    │  - user_payload: { units, allowed_speakers, candidates }
    │  - LLM vê units isolados, sem contexto cross-unit
    │  - Sem regras de 1ª pessoa, sem turn-taking
    │
    ▼
QA (per unit) → pass/fail
    │
    ▼
Interpretation (per unit, LLM) → Dialogue objects
```

## Goals / Non-Goals

**Goals:**
- Eliminar o colapso de diálogos no `narrator` para textos sem marcação explícita
- Reduzir chamadas LLM de attribution em 60–80% (units "dialogue" resolvidos por código)
- Manter compatibilidade com resume (manifest.json, scene_hash cache keys)
- Manter a arquitetura modular (sem acoplamento entre módulos)
- Não alterar o formato de output (LLMChapterResponse, Dialogue)

**Non-Goals:**
- Não alterar o pipeline de TTS ou merge
- Não adicionar novos modelos de embedding
- Não modificar o sistema de voices ou personagens
- Não alterar o formato de story.json
- Não mudar a estrutura de cache (continua keyed por scene_hash)

## Decisions

### Decision 1: Classificação prévia 4 classes (determinística)

**Decisão:** Antes da attribution, cada unit é classificado por código em `narration`, `explicit_dialogue`, `indirect_dialogue`, `ambiguous`.

**Racional:**
- `narration` (3ª pessoa, sem marcador) → nunca precisa de LLM
- `explicit_dialogue` (aspas, travessão, 1ª pessoa) → precisa apenas de speaker_id
- `indirect_dialogue` → mapeado para narrator com estilo indireto
- `ambiguous` → só estes vão para LLM (~20% dos units)

**Alternativas consideradas:**
- 3 classes (sem "ambiguous") → não resolve o problema de units sem marcador
- LLM classifica units → contradiz o objetivo de reduzir LLM calls

### Decision 2: Turn Tracker como resolvedor de diálogos

**Decisão:** Units classificados como "dialogue" são atribuídos por um Turn Tracker determinístico, não por LLM.

**Racional:**
- Diálogos em romances seguem padrão alternado (A, B, A, B...)
- O Scene Graph já fornece `focus_entity` (quem está em foco)
- Rotação circular entre personagens ativos resolve 80%+ dos casos
- LLM só precisa resolver casos realmente ambíguos

**Alternativas consideradas:**
- CandidateGenerator Step 6 (contexto de cena) → mais tokens, ainda usa LLM
- Classificação por embedding → não disponível, dependência extra

### Decision 3: Turn Tracker usa rotação circular com foco narrativo

**Decisão:** O Turn Tracker implementa rotação circular (circular buffer) entre personagens ativos, com `focus_entity` como anchor.

```python
class TurnTracker:
    def track(self, scene_units: list[UnitClassification],
              active_speakers: list[str],
              focus_entity: str | None) -> list[TurnAttribution]:
```

- Se 0 ativos: todos `narrator`
- Se 1 ativo: todos esse personagem
- Se 2+: rotação circular (A, B, A, B...)
- `focus_entity` como primeiro turno de novo bloco
- `scene_graph.edges` para detecção de mudança de bloco

**Racional:**
- Simples, determinístico, sem LLM
- Rotação circular é padrão em diálogos de ficção
- Focus entity resolve o caso mais comum (personagem em foco fala primeiro)

**Alternativas consideradas:**
- Pronoun resolution por unidade → já existe (Step 3), mas insuficiente
- Embedding similarity por unidade → sem modelo disponível

### Decision 4: LLM apenas para disambiguação com contexto de cena

**Decisão:** O prompt de attribution é reescrito para receber **apenas units ambíguos** com contexto completo da cena.

```json
{
  "scene_text": "...",
  "all_classifications": { "narration": [...], "explicit_dialogue": [...], "ambiguous": [...] },
  "resolved_units": [
    { "index": 0, "class": "narration", "speaker": "narrator" },
    { "index": 1, "class": "explicit_dialogue", "speaker": "ayanokoji" },
    ...
  ],
  "ambiguity_units": [
    { "index": 12, "text": "O garoto estava sentado na cadeira." }
  ],
  "speakers": [
    { "id": "ayanokoji", "aliases": ["o jovem", "garoto"], "gender": "masculino" },
    { "id": "office-lady", "aliases": ["a mulher"], "gender": "feminino" }
  ],
  "turn_history": [0: "ayanokoji", 2: "office-lady", 4: "ayanokoji", ...]
}
```

**Racional:**
- LLM recebe contexto completo para disambiguar com precisão
- Contexto de turn_history ajuda a detectar padrões de alternância
- Units já resolvidos são apresentados como "fatos consumados" (não podem ser mudados)

**Alternativas consideradas:**
- Attribution scene-level (tudo de uma vez) → prompt maior, mais risco de erro de schema
- Unit-classifier + LLM por unit ambíguo (sem contexto) → menos preciso

### Decision 5: QA por cena em vez de por unit

**Decisão:** O QA opera no nível de cena, não de unit individual.

**Racional:**
- Narrator collapse é um padrão cross-unit (vários units consecutivos colapsados)
- QA por unit individual não detecta este padrão
- QA por cena pode verificar:
  - Ratio narrator/dialogue
  - Alternância de speakers
  - Closed-set validation (incluindo Turn Tracker)

**Alternativas consideradas:**
- Manter QA por unit → não detecta collapse, já observamos o problema
- QA por cena com fallback unit-level → mais complexo, sem ganho

### Decision 6: Novo módulo `llm/turn_tracker.py` e `llm/unit_classifier.py`

**Decisão:** Separar responsabilidades em novos módulos, seguindo o padrão do projeto (SRP, arquivos <300 linhas).

**Novos módulos:**
- `llm/unit_classifier.py` — Classificação 4 classes (narration, explicit_dialogue, indirect_dialogue, ambiguous)
- `llm/turn_tracker.py` — Turn Tracker (rotação circular, focus entity)

**Módulos alterados:**
- `llm/candidate_generator.py` — Novo Step 0 (1ª pessoa)
- `llm/attribution.py` — Reduzido a disambiguação (apenas units ambíguos)
- `llm/ollama_backend.py` — Nova fase no pipeline (`_process_scene_v2_hybrid`)
- `llm/speaker_qa.py` — QA por cena
- `llm/prompts/attribution.md` — Prompt reescrito para disambiguação

**Novos modelos em `models/cast.py`:**
- `UnitClassification` — resultado do Unit Classifier
- `TurnAttribution` — resultado do Turn Tracker

## Risks / Trade-offs

### [Risk] Turn Tracker com rotação circular errada em diálogos não alternados

**Cenário:** Cena com 3 personagens onde um fala 3 turnos seguidos (A, A, A, B, C).

**Mitigação:**
- QA por cena detecta: se o texto tem evidência de 3+ falantes mas apenas 1 foi atribuído
- O Turn Tracker recebe contexto de `scene_graph.edges` (quem interage com quem)
- Units ambíguos (incluindo os "não alternados" classificados errado) são reenviados para LLM
- Debug output permite diagnóstico pós-run

### [Risk] Classificador 1ª pessoa falso-positive em narração

**Cenário:** Unidade "Eu me perguntei se ele estava bravo" é narração em 1ª pessoa do protagonista, mas o livro é narrado por um personagem.

**Mitigação:**
- Se o livro tem personagem POV (1ª pessoa narrador), o CharacterProfile inclui `role: "POV"`
- O Turn Tracker respeita POV: se há um narrador POV, diálogos vão para ele
- QA por cena verifica: se narrator POV está presente, colapso é esperado (não erro)

### [Risk] Breakage de cache existente

**Cenário:** Caches de attribution keyed por `scene_hash` + `candidate_generator_version` não reconhecem novo Step 0.

**Mitigação:**
- Bump de `ATTRIBUTION_POLICY_VERSION` invalida caches existentes
- Bump de `CANDIDATE_GENERATOR_VERSION` (adicionar "-fp" para first-person)
- Resume funciona: manifest.json ainda é válido, apenas attribution é recalculada

### [Risk] Aumento de complexidade do pipeline

**Cenário:** Mais módulos = mais pontos de falha, mais difícil de debugar.

**Mitigação:**
- Debug output por cena (`debug_scene_<id>.json`) com métricas de resolução
- Cada módulo é independente e testável isoladamente
- Pipeline v2 existente já tem 7 fases; adicionamos 2 novas (classificação + turn tracker)

## Migration Plan

### Fase 1: Novos módulos (sem breaking changes)

1. Criar `llm/unit_classifier.py` — classificação 4 classes
2. Criar `llm/turn_tracker.py` — turn tracker
3. Adicionar Step 0 em `llm/candidate_generator.py` — 1ª pessoa
4. Adicionar modelos `UnitClassification`, `TurnAttribution` em `models/cast.py`
5. Criar prompts `unit_classification.md` (opcional, classificador é 100% code)

### Fase 2: Pipeline híbrido

6. Modificar `_process_scene` em `llm/ollama_backend.py` para incluir:
   - Fase 3b: Unit Classification
   - Fase 5b: Turn Tracking
7. Modificar `llm/attribution.py` para receber units já resolvidos + units ambíguos
8. Modificar `llm/speaker_qa.py` para QA por cena

### Fase 3: Prompts e debug

9. Reescrever `llm/prompts/attribution.md` — disambiguação com contexto
10. Adicionar debug output (`debug_scene_*.json`) com métricas
11. Bump `ATTRIBUTION_POLICY_VERSION` e `CANDIDATE_GENERATOR_VERSION`

### Fase 4: Testes e validação

12. Criar testes para Unit Classifier
13. Criar testes para Turn Tracker
14. Criar testes para QA por cena
15. Validar com capítulo 5 (caso de teste: paste_1.txt)
16. Medir redução de LLM calls (esperado: 60–80% menos)

### Rollback

- Feature flag `SPEAKER_RESOLUTION_V2_ENABLED` já existe
- Setar `HYBRID_ATTRIBUTION_ENABLED=False` para reverter ao pipeline v2 antigo
- Caches antigos são válidos para o pipeline v2

## Open Questions

1. **POV detection:** Como saber se o narrador é um personagem POV (1ª pessoa)? O CharacterProfile pode incluir `role: "POV"`, mas isso precisa ser inferido no Cast Discovery. Atualmente, Cast Discovery é "frio" (sem inferências). → Resolver na fase 3 (enriquecer Cast Discovery com `role: "POV"` detection)

2. **Thresholds do Turn Tracker:** Quantos turnos antes de resetar a rotação? Quando alternar para outro personagem se há 3+ ativos? → Default: rotação circular simples; ajustar após validação

3. **Discurso indireto:** Unidades classificados como `indirect_dialogue` — como a Interpretation Pass os trata? → Manter comportamento atual (narrator + estilo indireto)
