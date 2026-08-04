## Why

A passagem única de interpretação pede ao LLM descobrir personagens e atribuir falas ao mesmo tempo. Em light novels em 1ª pessoa (ex. `ch-005` do Classroom), o modelo consegue popular o cast/`voice_profile` e ainda assim colapsar falas desses personagens em `narrator`. Descoberta de elenco precisa preceder a atribuição de speakers.

## What Changes

- Introduzir Pass 1 (character/cast discovery) antes da interpretação/diarização: capítulo-fonte completo (ou chunking de cobertura total se o contexto não couber; nunca head+tail); mapear personagens, aliases e participação chapter-local speaker vs mentioned, reusando o `story_state`.
- Pass 2 (interpretação) recebe um **conjunto fechado** de speakers (`narrator` ∪ falantes do capítulo; mentioned-only fora) e deixa de descobrir personagens novos no mesmo JSON de diálogos.
- `narrator` passa a significar apenas narração — não fallback para fala incerto/não resolvida.
- Estender o speaker QA para detectar colapso de diálogo em `narrator`; retries MVP retentam só Pass 2 com o mesmo cast (sem refresh automático de Pass 1).
- Cache/resume separados (ou versionados) para Pass 1, sem reexecutar discovery desnecessariamente e sem regenerar vozes duplicadas.
- Bump de política de diarização/cache para invalidar interpretações single-pass ruins.
- Fixture/regressão baseada na cena do ônibus de `ch-005`.

## Capabilities

### New Capabilities
- `cast-discovery`: Passagem LLM focada em descobrir/resolver o elenco do capítulo (cobertura completa do texto; participação speaker/mentioned chapter-local) antes da diarização, com saída pequena, cacheável e integrada ao `story_state`.

### Modified Capabilities
- `llm-interpretation`: Orquestração two-pass (cast → interpret); prompt Pass 2 com speaker set = narrator + falantes; semântica de `narrator`; narrator-collapse com retry Pass 2 apenas; política de cache alinhada.
- `interpret-resume`: Progresso/resume deve considerar discovery + interpret (não só a passagem única atual), sem skip cego após mudança de política.
- `story-state`: Reuso de personagens conhecidos e merge do chapter cast no estado persistido sem duplicar identidades/aliases.

## Impact

- Código: `llm/ollama_backend.py`, prompts sob `llm/prompts/`, modelos Pydantic de resposta LLM, `speaker_qa.py`, `config.py` (versão de política), `pipeline.py` / `interpret_progress`, testes + fixture `ch-005`.
- Comportamento: ~1 chamada LLM extra por unidade/capítulo na Pass 1 (saída curta); Pass 2 permanece a chamada pesada. Caches single-pass antigos missam após bump.
- Voice design: continua lazy após personagens existirem no story; two-pass NÃO deve disparar geração duplicada.
- Sem troca de modelo TTS; sem hardcode por capítulo; `qwen3:8b` permanece default viável (27b opcional via CLI).
