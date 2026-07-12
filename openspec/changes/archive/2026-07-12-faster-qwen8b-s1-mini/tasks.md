## 1. Config e registry de pesos

- [x] 1.1 Alterar `DEFAULT_OLLAMA_MODEL` para `qwen3:8b`; defaults de produto `TTS_MAX_CHUNK_CHARS=200` e `FISH_BEFORE_LOAD_TARGET_MIB=8192`
- [x] 1.2 Criar registry em `weights/fish.py` com aliases `s1-mini` e `s2-pro` (repo, revision pinada, required_files, logical cache id distinto `fish-s1-mini` / `fish-s2-pro`); default alias `s1-mini`
- [x] 1.3 Presets por alias (chunk/load) aplicados no pipeline/CLI só quando o usuário não overrideou chunk ou fish load
- [x] 1.4 Melhorar erro de download gated HF (mensagem: login + aceite S1-mini)

## 2. CLI e wiring

- [x] 2.1 Adicionar `--fish-model` / `AUDIOBOOK_AI_FISH_MODEL` em `cli.py`; validar aliases; passar ao pipeline/ModelManager/TTS
- [x] 2.2 Garantir que worker/job Fish recebe o path/logical id do alias selecionado (caches não misturam)

## 3. Testes e docs

- [x] 3.1 Testes do registry (ambos aliases), CLI inválida, presets vs override, fixtures S1-mini + s2-pro
- [x] 3.2 Atualizar testes que hardcodam defaults antigos (`qwen3.6:27b`, load 22528 único, chunk 80 único, repo só s2-pro)
- [x] 3.3 Atualizar `README.md` e `docs/SMOKE.md` (`--model` + `--fish-model`, HF gated, presets)

## 4. Verificação

- [x] 4.1 Rodar testes unitários relevantes
- [x] 4.2 Spike S1-mini (auth HF): ensure + load + 1 síntese; anotar SHA e MiB; ajustar se preciso
- [x] 4.3 Confirmar preflight default `qwen3:8b` e smoke mental `--fish-model s2-pro` (cache s2 já existente ok)
