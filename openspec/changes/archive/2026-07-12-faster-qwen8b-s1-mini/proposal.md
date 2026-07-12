## Why

Gerar um volume inteiro com `qwen3.6:27b` + Fish `s2-pro` na RX 7900 XTX (ROCm) leva dias: o TTS sozinho opera ~13× mais lento que realtime e o interpret de ~389k chars no 27b consome várias horas. Precisamos defaults mais rápidos sem abandonar o stack local (Ollama + Fish in-process), **e** poder voltar ao s2-pro (ou outro peso Fish open) sem rebuild — no mesmo espírito do `--model` do Ollama.

## What Changes

- **BREAKING (defaults):** `DEFAULT_OLLAMA_MODEL` passa de `qwen3.6:27b` para `qwen3:8b` (CLI `--model` continua podendo override).
- **BREAKING (defaults TTS):** pesos Fish default passam a **OpenAudio S1-mini**; `s2-pro` permanece disponível via CLI.
- **Nova opção CLI** `--fish-model` (env `AUDIOBOOK_AI_FISH_MODEL`) para escolher entre identidades Fish **open** registradas (MVP: `s1-mini` | `s2-pro`), análogo a `--model` do Ollama.
- ModelManager passa a resolver um **registry** de definições pinadas (repo, revision, required files, logical cache id) por alias `--fish-model`.
- Recalibrar defaults globais de VRAM / SpeechChunk para o footprint do S1-mini; ao selecionar `s2-pro`, aplicar presets conhecidos (chunk/load) salvo override explícito do usuário.
- Atualizar preflight/docs/smoke/README: default Ollama + Fish, HF gated do S1-mini, exemplos `--fish-model s2-pro`.
- Testes de weights/TTS/LLM/CLI alinhados ao registry e à flag.

## Capabilities

### New Capabilities

- (nenhuma)

### Modified Capabilities

- `llm-interpretation`: default Ollama recomendado/configurado muda para `qwen3:8b`.
- `model-manager`: registry de pesos Fish open (S1-mini + s2-pro) com revision/required files por alias; default S1-mini.
- `tts-fish-speech`: engine in-process carrega o path do alias selecionado via ModelManager.
- `vram-guardian`: default de load target do Fish recalibrado para S1-mini; preset s2-pro restaura target alto quando esse alias é escolhido (sem override).
- `generate-cli`: adiciona `--fish-model`; default `s1-mini`; documenta paralelos com `--model`.
- `preflight-checks`: default Ollama `qwen3:8b`; mensagens/docs mencionam `--fish-model` / HF gated quando aplicável.
- `speech-chunking`: default de `TTS_MAX_CHUNK_CHARS` para S1-mini; preset s2-pro pode usar limite menor quando esse alias é ativo sem override.

## Impact

- Código: `config.py`, `weights/fish.py` (registry), `cli.py`, `pipeline.py` / ModelManager wiring, testes, `docs/SMOKE.md`, `README.md`.
- Runtime: S1-mini exige **HF login + gated**; s2-pro continua no cache separado por logical id.
- Qualidade/velocidade: tradeoff explícito via flags (`--model` + `--fish-model`).
- Pipeline em andamento: cache LLM por modelo Ollama; caches Fish por alias não se sobrescrevem.
