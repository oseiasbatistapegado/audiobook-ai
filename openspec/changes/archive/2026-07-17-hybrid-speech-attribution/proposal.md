## Why

O pipeline de attribution por cena (v2) colapsa diálogos de personagens no `narrator` quando não há marcação explícita (`disse X`) no texto — o que é o padrão em romances japoneses traduzidos onde diálogos aparecem sem atribuição de falante por vários turnos consecutivos. A LLM recebe units isolados sem contexto de conversação, o CandidateGenerator é cego a marcadores de 1ª pessoa, e o QA opera por unit individual, não por cena.

## What Changes

- **Nova etapa determinística pré-attribution**: Classificação por unit de "narration", "dialogue", "ambiguous" usando marcadores de 1ª pessoa (`eu`, `meu`, `sou`, `por que eu`), `?`/`!`, e padrões de vocativo
- **Turn Tracker**: Para cada cena, um tracker alternado determina qual personagem fala em cada turno de diálogo consecutivo (rotação entre personagens conhecidos, com fallback para focus_entity)
- **LLM disambiguação**: Apenas units "ambíguos" são enviados à LLM, com contexto completo da cena (units vizinhos, personagens, padrões de alternância)
- **Unit "dialogue" sem LLM**: Units classificados como "dialogue" são atribuídos diretamente pelo Turn Tracker, sem chamada LLM — eliminando o colapso para narrator
- **CandidatGenerator Step 0**: Detecção de marcadores de 1ª pessoa como sinalizador de diálogo

## Capabilities

### Modified Capabilities

- `speaker-resolution`: Novos requisitos sobre classificação determinística pré-attribution, turn tracking, e LLM disambiguação (em vez de attribution pura)
- `scene-graph`: O Scene Graph passa a alimentar o Turn Tracker com foco narrativo e entidades ativas por cena

## Impact

- `llm/attribution.py` — reescrita parcial (atribuição reduzida a disambiguação)
- `llm/candidate_generator.py` — novo Step 0 (1ª pessoa)
- Novo módulo `llm/turn_tracker.py` — turn tracking por cena
- Novo módulo `llm/unit_classifier.py` — classificação determinística pré-attribution
- `llm/speaker_qa.py` — QA por cena em vez de por unit
- `llm/prompts/attribution.md` — prompt reduzido a disambiguação
- `llm/prompts/interpret_chapter.md` — já isolado, sem mudança
