## 1. TTS release API

- [x] 1.1 Adicionar `release()` (no-op) em `TTSBackend`
- [x] 1.2 Implementar `FishSpeechBackend.release()` (drop engine, gc, `empty_cache`, `_loaded=False`)
- [x] 1.3 Separar ensure de pesos em disco do load do engine (pipeline pode cachear sem ocupar VRAM)
- [x] 1.4 Testes: release idempotente; synthesize após release recarrega sem novo download (mocks)

## 2. Ollama unload API

- [x] 2.1 Adicionar `unload()` em `OllamaBackend` (keep_alive=0 / stop do modelo)
- [x] 2.2 Tornar unload idempotente e não-fatal (log warning em falha)
- [x] 2.3 Testes com client mock: unload após chat; unload com modelo já ausente

## 3. Orquestração do pipeline

- [x] 3.1 Remover eager load do engine antes do loop; manter ensure de pesos + progresso
- [x] 3.2 Por capítulo: `release` TTS → interpret → `unload` Ollama → load TTS → synthesize × N → `release` TTS
- [x] 3.3 Notificar progresso/logging nas etapas de handoff (`release-tts`, `unload-llm`, `load-tts`)
- [x] 3.4 Omitir unload Ollama em cache-hit de interpret (ou chamar só se houve chamada real)
- [x] 3.5 Testes de pipeline com backends fake: ordem de release/unload/load por capítulo e sem release entre segmentos

## 4. Verificação

- [x] 4.1 Atualizar/estender testes existentes de TTS, LLM e pipeline quebrados pela nova API
- [ ] 4.2 Smoke manual em GPU 24 GB: `ollama ps` com fração GPU alta no interpret; Fish Speech só na fase TTS; gerar sample
