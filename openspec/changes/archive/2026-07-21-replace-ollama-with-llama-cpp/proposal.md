## Why

O projeto usa `ollama` como backend LLM para interpretação de capítulos. O usuário
utiliza `llama-server` do `llama.cpp` com um Personal Access Token do Hugging Face
para gerenciar modelos GGUF, e o `llama.cpp` se encaixa melhor na arquitetura do
projeto — especialmente no ciclo de vida GPU: o servidor pode ser iniciado sob
demanda para interpretar todos os capítulos, encerrado para liberar VRAM, e então o
worker de TTS assume.

## What Changes

- Substituir `ollama` (cliente Python) pelo `llama.cpp` HTTP server (`llama-server`)
- Substituir `check_ollama()` por `check_llama_server()` no preflight
- Renomear `OllamaBackend` → `LlamaCppBackend` (mesma interface `LLMBackend`)
- Adicionar ciclo de vida do server: **start → interpretar → stop** entre fases LLM e TTS
- Remover dependência `ollama>=0.6.2` do `pyproject.toml`; adicionar `requests` (se necessário)
- Adaptar testes unitários (`test_llm.py`, `test_preflight.py`) para os novos mocks
- Atualizar CLI: `--ollama-host` → `--llama-host`, `--model` mantém comportamento
- Atualizar documentação: README, SMOKE, AGENTS, SMOKE.md

## Capabilities

### Modified Capabilities
- `preflight-checks`: O sistema SHALL verificar que `llama-server` está acessível e que
  o modelo GGUF existe no disco, em vez de verificar o API `/api/tags` do Ollama.

## Impact

| Categoria | Impacto |
|-----------|---------|
| **Código** | `ollama_backend.py` → `llama_cpp_backend.py`, `cli.py`, `pipeline.py`, `preflight.py`, `config.py`, `llm/__init__.py`, `attribution.py` |
| **Testes** | `test_llm.py`, `test_preflight.py` |
| **Dependências** | Remover `ollama`, adicionar `httpx` ou `requests` |
| **CLI** | `--ollama-host` → `--llama-host` (breaking para quem passa flag explicitamente) |
| **Config** | `DEFAULT_OLLAMA_MODEL` → `DEFAULT_LLAMA_MODEL`, `DEFAULT_OLLAMA_HOST` → `DEFAULT_LLAMA_HOST`, remoção de `OLLAMA_KEEP_ALIVE` |
| **Docs** | README.md, docs/SMOKE.md, AGENTS.md |
| **VRAM handoff** | `llm_backend.unload()` → `llama_server.terminate()` (novo mecanismo) |
