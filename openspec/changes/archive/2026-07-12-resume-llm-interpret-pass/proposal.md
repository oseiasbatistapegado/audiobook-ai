## Why

Reiniciar `generate` no meio do Pass A (interpretação) hoje reprocessa todos os capítulos desde o início: não há resume de interpretação, e o cache LLM erra com frequência porque a chave inclui o `story_state` completo — que já está populado no restart. Além disso, o pipeline descarrega o Ollama após cada capítulo mesmo quando o próximo passo ainda é interpretar, pagando reload do modelo 27B e invalidando a expectativa de `keep_alive=-1`. Com livros longos (~90 unidades LLM), isso torna interrupções e restarts proibitivamente caros.

## What Changes

- Persistir progresso de interpretação por capítulo (book-scoped) e **pular capítulos já interpretados** no restart, reutilizando `story.json` + chunks já no manifest.
- Tornar a **chave de cache LLM estável** face a crescimento do `story_state` (não hashear o dump completo volátil), preservando invalidação por modelo/unidade/política.
- **Adiar unload do Ollama** no Pass A: não descarregar após todo capítulo; descarregar apenas quando Voice Design precisa da GPU ou antes da fase TTS contínua.
- Manter exclusão mútua VRAM (LLM ≠ Voice Design ≠ TTS); apenas reduzir unloads desnecessários entre capítulos só-LLM.
- Sem **BREAKING** de CLI/API pública; work-dirs antigos sem marcador de progresso reinterpretam (seguro, mais lento) ou inferem skip a partir do manifest quando possível.

## Capabilities

### New Capabilities

- `interpret-resume`: Resume do Pass A — skip de capítulos já interpretados com sucesso, persistência book-scoped do progresso de interpretação, e comportamento seguro em capítulos parciais/interrompidos.

### Modified Capabilities

- `llm-interpretation`: Política de chave de cache LLM deixa de depender do `story_state` completo volátil; continua invalidando por modelo, unidade, e políticas de adaptação/diarização.
- `vram-handoff`: Unload Ollama deixa de ser obrigatório após cada capítulo; torna-se obrigatório antes de Voice Design (quando houver trabalho GPU) e antes da fase TTS contínua.
- `chunk-resume`: Clarificar que resume de chunks TTS permanece; Pass A passa a ter resume próprio sem re-emitir chunks de capítulos já cobertos.

## Impact

- `src/audiobook_ai/pipeline.py` — loop Pass A (skip + unload condicional)
- `src/audiobook_ai/llm/ollama_backend.py` — chave de cache
- `src/audiobook_ai/state/` (novo ou extensão de story/manifest) — progresso de interpretação
- `openspec/specs/llm-interpretation`, `vram-handoff`, `chunk-resume`
- Testes de pipeline/LLM/resume; smoke de restart mid-book
- Work em andamento (ex.: Classroom) deixa de re-pagar Cover/Cap.1 ao reiniciar após a change
