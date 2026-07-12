## Why

No mesmo processo de `generate`, Fish Speech (~22 GB VRAM) e Ollama (`qwen3.6:27b`) disputam a GPU. O pipeline carrega o TTS antes do interpret; Ollama encontra ~4 GiB livres e faz offload (~92% CPU / 8% GPU), deixando a interpretação ~2 tok/s. Em GPUs de 24 GB os dois modelos não cabem juntos — o handoff de VRAM é necessário para o LLM e o TTS usarem a GPU em turnos.

## What Changes

- O pipeline passa a **liberar a VRAM do TTS** antes de cada fase `interpret` (Ollama) e a **recarregar o engine TTS** só quando for sintetizar.
- Após a fase LLM de um capítulo (ou ao entrar na fase TTS), o sistema **libera o modelo Ollama da memória** (ex.: `keep_alive=0` / stop) para o Fish Speech voltar a caber na GPU.
- `FishSpeechBackend` ganha API explícita de **release/unload** do engine em GPU (pesos em disco permanecem via ModelManager; download continua uma vez).
- A regra “load único do engine por geração” é **substituída** por: download/cache único; engine GPU pode ser descarregado e recarregado entre fases LLM ↔ TTS; **sem** reload entre segmentos TTS consecutivos na mesma fase.
- Eager `ensure_ready()` antes do loop de capítulos deixa de manter o engine residente: pode validar/cachear pesos sem ocupar VRAM até o primeiro TTS.
- Logging/progresso indica handoff (release TTS / unload LLM / reload TTS) quando ocorrer.

## Capabilities

### New Capabilities

- `vram-handoff`: Orquestração de exclusão mútua de VRAM entre fases LLM (Ollama) e TTS (Fish Speech) no pipeline `generate` — release, reload e sinais de progresso.

### Modified Capabilities

- `tts-fish-speech`: Permitir unload/reload do engine GPU entre fases; manter reuso sem reload entre segmentos consecutivos; download de pesos continua único via ModelManager.
- `llm-interpretation`: Após interpretação (ou sob pedido do pipeline), o backend Ollama MUST poder liberar o modelo da memória/VRAM para não bloquear o TTS.
- `generate-cli`: Progresso/logging das etapas de handoff de VRAM quando o pipeline as executa.

## Impact

- Código: `pipeline.py`, `FishSpeechBackend` / `TTSBackend`, `OllamaBackend`, possivelmente factory/tests de TTS e preflight.
- Runtime: RX 7900 XTX 24 GB (e GPUs similares) — interpret e TTS em série na GPU; custo de reload do Fish Speech por capítulo (ou por transição de fase).
- Sem mudanças de API CLI pública obrigatórias; sem novos deps externos além da API já usada do Ollama.
- Spec `tts-fish-speech` “Load único e reuso” deixa de proibir reload após release intencional.
