## Context

O projeto `audiobook-ai` converte PDFs de livros em audiolivros (M4B). A fase de
interpretação LLM usa `ollama` como backend — um processo local que roda modelos
GGUF via API HTTP. O cliente Python (`ollama` package) envia mensagens e recebe
JSON validado por Pydantic.

O pipeline serial é: `PDF → capítulos → Ollama (interpretação) → SpeechChunks →
TTS workers → merge → M4B`. O VRAM handoff entre fases LLM e TTS usa
`keep_alive=0` do Ollama para descarregar o modelo da GPU.

O usuário agora roda `llama-server` (do `llama.cpp`) com MTP speculative decoding,
um Personal Access Token do Hugging Face, e prefere o ecossistema `llama.cpp`.

## Goals / Non-Goals

**Goals:**
- Substituir `ollama` → `llama.cpp` (HTTP server + Python client via `httpx`)
- Manter a interface `LLMBackend` inalterada (`interpret_chapter()`, `unload()`)
- Preservar o ciclo de vida: **start server → interpretar capítulos → stop server → TTS**
- Manter compatibilidade com pipeline v2 (scene-based, hybrid attribution)
- Manter MTP speculative decoding (`--spec-type draft-mtp --spec-draft-n-max 4`)

**Non-Goals:**
- Substituir o TTS backend (Qwen3-TTS permanece)
- Modificar a estrutura de prompts (`.md` files sob `llm/prompts/`)
- Alterar o ciclo de vida dos workers TTS (já usam subprocess + LifecycleManager)
- Adicionar suporte a outros backends LLM (vLLM, Text Generation Inference, etc.)

## Decisions

### D1: `llama-server` como subprocess controlado pelo pipeline

```
Pipeline (Python)
  ┌──────────────┐
  │ run_generate │
  └──────┬───────┘
         │
  ┌──────▼───────┐
  │ Popen(server)│  ← llama-server com args + HF_TOKEN
  └──────┬───────┘
         │
  ┌──────▼───────┐     ┌──────────────────────┐
  │ LlamaCpp     │────▶│ POST /v1/chat/complet │
  │ Backend      │◀────│ /{"choices": [...]}  │
  └──────┬───────┘     └──────────────────────┘
         │
  ┌──────▼───────┐
  │ terminate()  │  ← server_proc.terminate() + wait()
  └──────────────┘
```

**Rationale**: `llama-server` já é o binário que o usuário usa. Subprocess
`Popen` dá controle total do ciclo de vida, sem código extra de servidor.
Manter a API HTTP (OpenAI-compatible) evita mudanças no formato de request/response.

### D2: `httpx` como cliente HTTP (em vez de `requests`)

`httpx` já é uma dependência de `httpx` (assíncrona, mas com API síncrona
`httpx.Client()`). Útil se o projeto migra para async no futuro.
Alternativa: `requests` é mais simples, mas é dependência extra.

**Decisão**: Usar `httpx` (síncrono via `httpx.Client()`). Se o projeto já
não tiver `httpx`, adicionar ao `pyproject.toml`.

### D3: Ciclo de vida do server

```
  run_preflight()         → verifica binário `llama-server` e modelo GGUF
  run_generate()
    _start_llama_server()  → Popen com:
      - model, ctx_size, ngg, fa, spec-type, parallel, kv-unified
      - chat-template jinja
      - HF_TOKEN da env
    for chapter in chapters:
      llm_backend.interpret_chapter(chapter, story)
    _stop_llama_server()   → terminate() + wait()
    ... TTS phase ...
```

**Rationale**: O servidor vive apenas durante a fase de interpretação. Ao
encerrar, a VRAM é liberada automaticamente (processo termina).

### D4: Chat format

O Qwen3.6 usa o template `@` do `chatml`. `llama-server` roda com `--jinja`
e o Python client usa `chat_format="chatml"` para garantir formatação
correta das mensagens.

### D5: `unload()` como no-op

`LlamaCppBackend.unload()` não precisa chamar `generate(keep_alive=0)` —
o servidor é encerrado pelo pipeline antes do TTS. `unload()` é um
**no-op** (mesmo comportamento default da base `LLMBackend`).

### D6: Preflight muda de `/api/tags` para `/health`

`llama-server` expõe `GET /health` (200 OK) para verificar disponibilidade.
Para verificar qual modelo está carregado, usar `GET /v1/models` (responde
com `data: [{"id": "..."}]` ou similar).

### D7: Model path

O GGUF já está em disco (`~/.cache/huggingface/hub/...`) — o
`llama-server` aceita `--model` com caminho absoluto. Confirmado pela
pasta paste_1.txt do usuário.

## Risks / Trade-offs

| Risk | Impacto | Mitigação |
|------|---------|-----------|
| `llama-server` crash durante interpretação | Perda de progresso do capítulo | O pipeline já tem retry por JSON inválido; se o server cair, tratar como erro fatal com mensagem clara |
| Modelo GGUF não existe no disco | Pipeline falha no start do server | `run_preflight` verifica `Path(model_path).is_file()` antes de começar |
| Chat template incompatível | Respostas LLM com JSON inválido | Validar com `chat_format="chatml"`; garantir que o template do Qwen3 é respeitado |
| VRAM leak no server | TTS falha ao não encontrar VRAM suficiente | `LifecycleManager` já faz polling de VRAM antes de qualquer GPU work |
| HF_TOKEN não setada | Server não baixa/inicializa modelo | `HF_TOKEN` já é env var; garantir que é passado ao Popen env |

## Migration Plan

1. Criar `llama_cpp_backend.py` (task 1)
2. Adicionar `_start_llama_server` / `_stop_llama_server` ao pipeline (tasks 2-3)
3. Atualizar `cli.py` — flags `--llama-host`, `--llama-model` (task 4)
4. Atualizar `preflight.py` — `check_llama_server()` (task 5)
5. Adaptar módulos dependentes (task 6)
6. Adaptar testes (task 7)
7. Atualizar docs (task 8)
8. **Smoke manual** — `generate <pdf>` completo (task 9)

**Rollback**: Manter `ollama_backend.py` renomado para `.bak` por 2 sprints.
Se algo falhar no smoke, reverter as mudanças do CLI/preflight/pipeline.

## Open Questions

1. **Chat template**: O Qwen3.6 usa o template `@` do `chatml`. Garantir que
   `llama-server` roda com `--chat-template jinja` e o Python client usa
   `chat_format="chatml"` para formatação correta das mensagens.
2. **Config do pyproject.toml**: O extra `tts-qwen` não usa `ollama` — então a
   dependência `ollama>=0.6.2` é removida de `pyproject.toml` globalmente.
