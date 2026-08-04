## Why

O smoke com `Qwen/Qwen3-TTS-12Hz-0.6B-Base` em Voice Clone aprovou PT-BR com referências Parler existentes (~3 GB VRAM na RX 7900 XTX), enquanto o Fish Speech permanece o ator de produto com custo maior, chunks pequenos e superfície operacional pesada. É o momento de substituir **somente o ator TTS**, mantendo Parler como Voice Designer e o restante do pipeline (diretor, registry, chunks, resume, lifecycle).

## What Changes

- **BREAKING:** Fish Speech deixa de ser backend TTS suportado; rollback apenas via Git (sem dual-backend / fallback).
- Adotar `Qwen3-TTS 0.6B Base` (`qwen3-tts`) como único ator TTS: Voice Clone sobre `reference.wav` + `reference.txt`.
- Generalizar a orquestração `run_fish_phase` / `run_fish_with_restarts` e ids arquiteturais `fish-speech` → `run_tts_*` / `tts`; usar `qwen3-tts` só para backend/modelo concreto.
- Remover código, deps, CLI (`--fish-model`), configs `FISH_*`, aliases `s1-mini`/`s2-pro` e docs/testes exclusivos do Fish.
- Tornar o extra Parler **autossuficiente** (DAC/`descript-audio-codec` sem depender de `fish-speech`); gate de remoção do Fish inclui Voice Design funcional sem Fish.
- Default inicial `TTS_MAX_CHUNK_CHARS=500` e `before_load_target_mib=6144`; calibrar chunks `500 → 1000 → 2000 → 4000` e load target (peak + margem) no hardware oficial; documentar impacto no `chunking_fingerprint`/resume.
- Preservar `Emotion` no domínio (`TTSRequest`, SpeechChunks, manifest, diretor); **não** mapear `Emotion → instruct` (API Base não oferece controle explícito).
- Avaliar expressividade **implícita** (texto semanticamente expressivo → prosódia inferida pelo Base) via gate perceptual; se insuficiente, abrir change separada — não expandir escopo aqui.
- Manter `VOICE_REF_MAX_SECONDS=6.0`, VoiceRegistry/VoiceProfile, worker isolation, LifecycleManager, VRAMGuardian, persist-before-reclaim e hard reclaim.

## Capabilities

### New Capabilities

- `tts-qwen3`: Ator TTS único via Qwen3-TTS 0.6B Base (Voice Clone), factory/`TTSBackend`, worker isolado, pesos pinados, tratamento de Emotion (metadata only) e gate de expressividade implícita.

### Modified Capabilities

- `tts-fish-speech`: **BREAKING** — capability retirada do produto; requisitos Fish removidos em favor de `tts-qwen3`.
- `gpu-lifecycle`: Fase TTS genérica (`run_tts_*`, backend arquitetural `tts`); políticas de restart/OOM/lease sem nomenclatura Fish.
- `model-manager`: Registrar `qwen3-tts` (repo + revision pinada); remover pesos/aliases Fish.
- `speech-chunking`: Default de produto `500`; remover presets Fish `s1-mini`/`s2-pro`; calibração documentada.
- `chunk-resume`: Documentar que mudança de `TTS_MAX_CHUNK_CHARS` altera fingerprint e invalida resume da fase TTS.
- `generative-voice-design`: Parler permanece; refs servem o ator Qwen3-TTS; independência de DAC/Fish; sem Voice Design Qwen nesta change.
- `preflight-checks`: Imports/runtime Qwen3-TTS (+ Parler/DAC) em vez de `fish_speech`.
- `vram-guardian`: Load targets / eventos da fase TTS com id arquitetural `tts` (e backend concreto `qwen3-tts` onde couber).
- `vram-handoff`: Handoff LLM ↔ fase TTS sem referências obrigatórias ao Fish.
- `generate-cli`: Remover `--fish-model` / env Fish; defaults e flags alinhados a Qwen3-TTS / `TTS_*`.
- `story-state`: Voice map / refs descritas como utilizáveis pelo ator TTS atual (Qwen3-TTS), não Fish.

## Impact

- Código: `tts/` (novo backend, factory), `workers/`, `weights/`, `gpu/{orchestrate,lifecycle,jobs,guardian}.py`, `pipeline.py`, `config.py`, `cli.py`, `preflight.py`, `pyproject.toml`/extras, testes e `docs/SMOKE.md`.
- Runtime: único motor TTS = Qwen3-TTS Base; Parler + Qwen instaláveis sem `fish-speech`.
- Domínio: contratos `TTSRequest`/`Emotion`/`VoiceProfile`/`SpeechChunk` preservados; Emotion não controla geração no Base.
- Follow-ups explícitos (fora de escopo): `evaluate-qwen3-tts-voice-design`, `evaluate-qwen3-tts-explicit-emotion-control`.
- Não inclui: CosyVoice, CustomVoice, VoiceDesign checkpoint, dual-backend, remoção do Parler.
