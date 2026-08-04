## 1. Infraestrutura de pesos e dependências

- [x] 1.1 Criar `weights/qwen3_tts.py` com logical id `qwen3-tts`, repository `Qwen/Qwen3-TTS-12Hz-0.6B-Base`, revision pinada e `required_files`
- [x] 1.2 Integrar `qwen3-tts` no `ModelManager` (registry neutro; sem depender de `FishSpeechModel`)
- [x] 1.3 Adicionar extra/deps de runtime Qwen3-TTS no `pyproject.toml` (substituir/paralelo a `tts-fish` até o corte)
- [x] 1.4 Validar download + import + load do modelo em ROCm no hardware oficial
- [x] 1.5 Em ambiente **sem** `fish-speech`, instalar só Parler + Qwen3-TTS; gerar ref Parler; identificar dependência de decode real
  - Runtimes isolados: Parler `.venv-parler` (`transformers==4.46.1`) × TTS (`.venv`, `transformers==4.57.3`). DAC = `descript-audio-codec==1.0.0`.
- [x] 1.6 Declarar/pinar essa dependência no extra `voice-parler`; registrar `DAC_PACKAGE` e `DAC_VERSION`
- [x] 1.7 Gate composto: sem Fish + Parler gera `reference.wav` + Qwen3-TTS clona → PASS (bloquear corte do Fish até passar)
  - `NEW CHARACTER PIPELINE GATE: PASS` via `scripts/gate17_new_character_pipeline.py` (2026-07-12).

## 2. Backend Qwen3-TTS

- [x] 2.1 Implementar `tts/qwen3_tts.py` (`Qwen3TTSBackend`) com `synthesize(TTSRequest) -> AudioSegment`
- [x] 2.2 Integrar `resolve_voice_dir` + `reference.wav` + transcript (`reference.txt`/`.lab`)
- [x] 2.3 Fixar `language` portuguese (ou valor oficial da API pinada) no Voice Clone
- [x] 2.4 Preservar `emotion` no request/metadata; **não** mapear para `instruct`/tags/hacks de sampling
- [x] 2.5 Atualizar `tts/factory.py`: único backend `qwen3-tts` (+ alias `qwen3tts`); rejeitar Fish/CosyVoice
- [x] 2.6 Atualizar defaults: `DEFAULT_TTS_BACKEND=qwen3-tts`, `TTS_MAX_CHUNK_CHARS=500`, load target TTS **6144 MiB**

## 3. Worker e orquestração genérica

- [x] 3.1 Criar `workers/qwen3_tts.py` (SpeechChunks, persist-before-reclaim, guardian hooks, expandable_segments)
- [x] 3.2 Renomear `run_fish_phase` → `run_tts_phase` e `run_fish_with_restarts` → `run_tts_with_restarts`
- [x] 3.3 Trocar id arquitetural `fish-speech` → `tts`; usar `qwen3-tts` só no backend/modelo
- [x] 3.4 Renomear configs `FISH_*` de política OOM/residency para `TTS_*` (budget, stall, chunks-per-worker)
- [x] 3.5 Atualizar `pipeline.py`, `gpu/jobs.py`, `gpu/lifecycle.py`, `gpu/orchestrate.py`, `gpu/guardian.py`
- [x] 3.6 Validar hard reclaim (exit do worker) e resume via manifest na fase TTS
  - Coberto por `tests/test_qwen3_tts_worker.py` + `tests/test_gpu_lifecycle.py` (persist-before-reclaim, controlled restart, release verify).

## 4. Corte do Fish Speech

- [x] 4.1 Remover `tts/fish_speech.py`, `workers/fish_speech.py`, `weights/fish.py` **somente após** gate 1.7 PASS
- [x] 4.2 Remover extra `tts-fish`, pin/install docs de `fish-speech`, e dependência runtime
- [x] 4.3 Remover CLI `--fish-model` / env `AUDIOBOOK_AI_FISH_MODEL` e aliases `s1-mini`/`s2-pro`
- [x] 4.4 Remover mensagens/docs Fish (`README`, `docs/SMOKE.md`, preflight Fish)
- [x] 4.5 Remover ou reescrever testes exclusivos do backend Fish; atualizar testes de lifecycle/factory/CLI
- [x] 4.6 Confirmar que Parler continua funcional sem qualquer import/path Fish
  - Gate 1.7 PASS com `fish_speech` ausente; Voice Design em `.venv-parler`.

## 5. Chunking, CLI e documentação

- [x] 5.1 Aplicar default `TTS_MAX_CHUNK_CHARS=500` e load target **6144**; remover presets Fish de chunk/load
- [x] 5.2 Documentar que mudar `TTS_MAX_CHUNK_CHARS` altera `chunking_fingerprint` e invalida resume TTS
- [x] 5.3 Atualizar flags CLI de residency/VRAM para nomes `TTS_*` (sem `FISH_*`)
- [x] 5.4 Manter `VOICE_REF_MAX_SECONDS=6.0` sem alteração
- [x] 5.5 Atualizar SMOKE/README para pipeline Parler → Qwen3-TTS (incluir `DAC_PACKAGE`/`DAC_VERSION`)

## 6. Gates de qualidade e calibração

- [x] 6.1 Smoke PT-BR Voice Clone com refs Parler existentes (identidade perceptível); registrar VRAM before/after load/gen/release
  - Ver `out/gates/calibration_report.json` + `docs/QWEN3_TTS_GATE_NOTES.md` (2026-07-12).
- [ ] 6.2 Gate de expressividade implícita (mesma ref; categorias neutral/angry/sad/happy/fear/excited/whisper; sem instruct/tags/hacks)
  - Amostras geradas em `out/gates/expressiveness/`; **PENDING_HUMAN_LISTENING**.
- [ ] 6.3 Documentar `Implicit Expressiveness Gate: PASS|FAIL`; se FAIL, abrir follow-up `evaluate-qwen3-tts-explicit-emotion-control` sem expandir escopo
- [x] 6.4 Calibrar chunks `500 → 1000 → 2000 → 4000` registrando RTF, peak VRAM, success/failure, quality/prosody notes
  - Todos PASS; relatório em `out/gates/calibration_report.json`.
- [x] 6.5 Aplicar regra: default final = maior tamanho **sem regressão** vs último aprovado (não o maior que cabe na VRAM)
  - Default permanece **500** até A/B humano; 4000 cabe mas qualidade/prosódia pendente.
- [x] 6.6 Recalibrar `before_load_target_mib` = peak observado + margem; documentar valor final (inicial era 6144)
  - Peak calibração **8608 MiB** (chunk 2000); target produto mantido **6144** até smoke PDF→M4B + A/B.
- [ ] 6.7 Smoke pipeline completo PDF → Qwen3:8B → Parler → Qwen3-TTS → SpeechChunks → M4B
  - Bloqueado: sem `samples/sample.pdf` no repo.

## 7. Verificação final

- [x] 7.1 Suite de testes automatizados passando
- [x] 7.2 Confirmar ausência de dependência runtime `fish-speech` no caminho de produto
- [x] 7.3 Confirmar Emotion ainda presente em domínio/metadata e ausente como controle de geração no Base
- [x] 7.4 Revisar specs main sync readiness (capability `tts-qwen3` vs remoção `tts-fish-speech`) após implementação
  - `openspec/specs/tts-qwen3/` criado; `tts-fish-speech` removido; deltas aplicados às specs main.
