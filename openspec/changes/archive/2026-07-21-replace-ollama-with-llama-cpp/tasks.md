## 1. Preparar o backend LlamaCpp

- [x] 1.1 Criar `src/audiobook_ai/llm/llama_cpp_backend.py` com a classe `LlamaCppBackend`
  - Implementar `interpret_chapter()` e `interpret_chapter_v2()`
  - Substituir `ollama.Client.chat()` por `httpx.Client().post("/v1/chat/completions", ...)`
  - Manter `_chat()` como método interno que extrai `choices[0].message.content`
  - Manter `unload()` como no-op (server é controlado pelo pipeline)
  - Copiar toda a lógica de validação, cache, retry, thinking recovery de `ollama_backend.py`
- [x] 1.2 Adicionar `httpx` como dependência em `pyproject.toml` (se não já presente)
- [x] 1.3 Remover `ollama>=0.6.2` de `pyproject.toml`

## 2. Adaptar o pipeline para lifecycle do server

- [x] 2.1 Criar `_start_llama_server()` no `pipeline.py`
  - `subprocess.Popen` com os args do comando do usuário (paste_1.txt):
    `--ngl 999 --fa on --spec-type draft-mtp --spec-draft-n-max 4 --no-mmap
    --ctx-size 153600 --batch-size 1024 --ubatch-size 512
    -ctk q4_0 -ctv q4_0 --parallel 1 --kv-unified
    --ctx-checkpoints 8 --checkpoint-every-n-tokens 2048
    --cache-ram -1 --cache-idle-slots --metrics --jinja
    -hft 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 -hf localweights/...`
  - Passar `HF_TOKEN` via env do subprocess
  - Guardar `server_proc` como atributo do pipeline (ou do backend)
  - Aguardar até `GET /health` responder 200
- [x] 2.2 Criar `_stop_llama_server()` no `pipeline.py`
  - `server_proc.terminate()` + `server_proc.wait(timeout=30)`
  - Tratar `TimeoutError` com `server_proc.kill()`
- [x] 2.3 Integrar start/stop no loop de interpretação de capítulos:
  - Iniciar server antes do primeiro capítulo
  - Interpratar todos os capítulos
  - Parar server depois do último capítulo, antes da fase TTS
  - Mover `llm_backend.unload()` → `_stop_llama_server()` no `_unload_llm()`

## 3. Atualizar o CLI

- [x] 3.1 Renomear `--ollama-host` → `--llama-host` em `cli.py`
- [x] 3.2 Renomear `--model` description de "Ollama model name" para "LLM model name"
- [x] 3.3 Atualizar string de ajuda do CLI (`app = typer.Typer(help=...)`) de "Ollama" para "llama-server"
- [x] 3.4 Garantir que `run_generate()` recebe `llama_host` em vez de `ollama_host`

## 4. Atualizar o preflight

- [x] 4.1 Renomear `check_ollama()` → `check_llama_server()` em `preflight.py`
- [x] 4.2 Substituir `_fetch_ollama_model_names()` por `_fetch_llama_server_models()`
  - `GET /health` para verificar disponibilidade (200 OK)
  - `GET /v1/models` para listar modelos carregados (data: JSON)
  - Ou: verificar `llama-server --model <path>` localmente
- [x] 4.3 Atualizar mensagens de erro para referenciar `llama-server` e não `ollama`
- [x] 4.4 Adicionar verificação de `llama-server` binário no PATH (como `check_ffmpeg`)
- [x] 4.5 Adicionar verificação de `HF_TOKEN` (se definida, verificar acesso ao repo HF)

## 5. Atualizar módulos que dependem de OllamaBackend

- [x] 5.1 Atualizar `src/audiobook_ai/llm/__init__.py`: re-export `LlamaCppBackend` em vez de `OllamaBackend`
- [x] 5.2 Atualizar `src/audiobook_ai/llm/attribution.py`: `_call_chat()` fallback para `LlamaCppBackend`
- [x] 5.3 Atualizar `src/audiobook_ai/config.py`:
  - `DEFAULT_OLLAMA_MODEL` → `DEFAULT_LLAMA_MODEL`
  - `DEFAULT_OLLAMA_HOST` → `DEFAULT_LLAMA_HOST`
  - Remover `OLLAMA_KEEP_ALIVE`
  - Adicionar `LLAMA_CPP_DEFAULT_PORT = "http://127.0.0.1:8080"`

## 6. Adaptar testes

- [x] 6.1 Atualizar `tests/test_llm.py`:
  - Mock de `httpx.Client` em vez de `ollama.Client`
  - Verificar `POST /v1/chat/completions` com JSON body
  - Testar response format `{"choices": [{"message": {"content": "..."}}]}`
- [x] 6.2 Atualizar `tests/test_preflight.py`:
  - `test_ollama_unreachable` → `test_llama_server_unreachable`
  - `test_ollama_model_missing` → `test_llama_server_model_missing`
  - Mock de HTTP em vez de `_fetch_ollama_model_names`
- [x] 6.3 Atualizar `tests/test_speaker_resolution.py`, `tests/test_qa_units.py`, `tests/test_speaker_integration.py`:
  - Import `LlamaCppBackend` em vez de `OllamaBackend`
- [x] 6.4 Rodar `uv run pytest` — todos os testes devem passar

## 7. Atualizar documentação

- [x] 7.1 Atualizar `README.md`: remover referências ao Ollama, adicionar `llama-server`
- [x] 7.2 Atualizar `docs/SMOKE.md`: instruções de start do `llama-server`
- [x] 7.3 Atualizar `AGENTS.md`: diagrama de arquitetura atualizado, referência a `llama_cpp_backend.py`
- [x] 7.4 Atualizar `openspec/specs/preflight-checks/spec.md` (delta spec já existe, verificar se está correto)

## 8. Smoke manual

- [x] 8.1 Start `llama-server` manualmente com os args do usuário (paste_1.txt)
- [x] 8.2 Executar `uv run audiobook-ai generate path/to/sample.pdf`
  - Verificar: interpretação LLM funciona, server para após capítulos
  - Verificar: TTS phase inicia normalmente com VRAM liberada
- [x] 8.3 Verificar resume: interromper pipeline no meio, re-run — deve pular capítulos já interpretados
