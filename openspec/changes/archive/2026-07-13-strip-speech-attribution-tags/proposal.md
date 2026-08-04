## Why

Em audiobook com vozes distintas por personagem, tags narrativas coladas na fala (`"Prova?, perguntou ela."`, `"…, disse ela."`) fazem o TTS ler atribuição com a voz do personagem. O speaker QA atual só rejeita conflito nome≠speaker; pronomes (`ela`/`ele`) e atribuições alinhadas ao speaker passam — o texto continua contaminado.

## What Changes

- Remover (não mover para narrador) speech-tags de atribuição do `dialogues[].text` de turnos de personagem: verbos do tipo `disse`/`perguntou`/`respondeu`/… + `ela`/`ele`/nome.
- Atualizar o prompt de interpretação para proibir tags de atribuição dentro do texto falado; a voz do turn já identifica o falante.
- Adicionar repair determinístico pós-LLM (strip) e invariante de QA que rejeita turnos de personagem que ainda carreguem speech-tag residual.
- Cobrir regressão com fixture derivada de `ch-004` (`disse ela` / `perguntou ela`).
- Bump da política de cache de interpretação para invalidar caches gerados sob a política anterior.

## Capabilities

### New Capabilities

<!-- nenhuma — comportamento entra em llm-interpretation -->

### Modified Capabilities

- `llm-interpretation`: prompt, repair e QA devem garantir texto falado sem tags de atribuição narrativa (opção “descartar tag”; não manter turno narrador separado para a tag).

## Impact

- `src/audiobook_ai/llm/prompts/interpret_chapter.md` — regras de diarização/texto falado
- `src/audiobook_ai/llm/speaker_qa.py` (e/ou módulo de repair adjacente) — strip + gate
- `src/audiobook_ai/llm/ollama_backend.py` — ordem repair → QA; bump de política de cache
- Testes/fixtures de speaker QA e, se aplicável, sanitize/repair
- Capítulos já interpretados em workdirs existentes só se beneficiam após re-interpretação (cache miss pela nova política)
