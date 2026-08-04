## Why

Com `qwen3:8b`, a interpretação aceita JSON schema-válido mas com speakers colapsados no protagonista (falas de Sudou/Ike/etc. viram `k-ayankoji`), e capítulos longos geram JSON truncado/inválido que aborta o `generate` inteiro após um único retry — antes mesmo da fase TTS. Precisamos manter o default `qwen3:8b` e tornar a diarização e a robustez de capítulos longos confiáveis o suficiente para audiolivros multi-personagem.

## What Changes

- Endurecer o prompt: prosa/1ª pessoa → `narrator`; fala explícita do POV → protagonist id; um falante por turno; reuso de ids + `story_updates` (semântica `speaker_id` ≠ `voice_id`).
- QA pós-schema com defaults fechados (`quoted_turns>=6` ∧ `dominance>=0.85` ∧ `evidence_of_multiple_speakers>=2`); fixture obrigatória `ch-011`.
- Particionar capítulos longos com `LLM_INTERPRET_MAX_CHARS=6000`; agregar `dialogues`/`story_updates` de forma determinística.
- Retries com `LLM_INTERPRET_MAX_ATTEMPTS=3` para JSON/schema/QA, sem upgrade obrigatório de modelo.
- Bump da política de cache de interpretação para invalidar caches ruins gerados sob as regras antigas.
- Manter `qwen3:8b` como default; modelo maior permanece opcional via CLI, não como dependência desta correção.

## Capabilities

### New Capabilities
- `interpret-unit-splitting`: Particionar capítulos acima de um limiar de tamanho em unidades de interpretação LLM ordenadas, interpretar cada unidade e reassentar o resultado no capítulo lógico.

### Modified Capabilities
- `llm-interpretation`: Contrato de atribuição de speaker, gate de QA semântica pós-schema, retries enriquecidos para JSON/schema/QA, e versionamento de política de cache alinhado às novas regras — ainda com default `qwen3:8b`.

## Impact

- Código: `llm/prompts/interpret_chapter.md`, `llm/ollama_backend.py`, `llm/sanitize.py` (e/ou novo módulo de QA), `pipeline.py` (orquestração por unidade), `config.py` (limiares/retries/versão de política), testes de interpretação/pipeline.
- Comportamento: interpret mais lento em capítulos longos (N chamadas), mas deixa de abortar o livro por um único JSON enorme; caches antigos de interpretação missam após bump de política.
- Sem mudança no backend TTS; Pass A → Pass B permanece, agora com Pass A mais resiliente.
- Sem dependência de modelo maior que `qwen3:8b`.
