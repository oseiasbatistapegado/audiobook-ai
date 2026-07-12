## 1. Config e primitivas de memória

- [x] 1.1 Centralizar em `config.py`: `hard_floor_mib=300`, `before_chunk_target_mib=768`, Fish `before_load_target_mib=22528`, Parler load-target placeholder calibrável (NÃO herdar Fish), `tts_max_chunk_chars`, progressive-growth `K=3`/`N=256`, Fish worker restart budget `3`, per-chunk attempts `2`
- [x] 1.2 Criar módulo `gpu/memory.py` com `VRAMSnapshot` e provider pluggable (system free + PyTorch alloc/reserved quando disponível)
- [x] 1.3 Criar `gpu/guardian.py` (`VRAMGuardian`) com `snapshot`, `can_start_chunk`, `can_load_backend`, `require_safe_headroom`, detector de progressive growth (janela K/N) e classificação de erros de memória
- [x] 1.4 Testes unitários do guardian com fake memory provider (floor, chunk target, load target por backend, janela de degradação sem falso positivo de sample isolado, mensagens distintas)

## 2. SpeechChunk e manifest/resume

- [x] 2.1 Definir modelo `SpeechChunk` (id estável, sequence, text, metadata) e função de partição com boundaries parágrafo → turno → sentença → split
- [x] 2.2 Implementar IDs/ordenação determinísticos + fingerprint de config de chunking
- [x] 2.3 Work-dir book-scoped `work/<book_id>/` (`book_id` = BLAKE2b-128 do conteúdo do input) com `audio/` + `manifest.json`; helpers de leitura/atualização; output path do usuário não define `book_id`
- [x] 2.4 Implementar skip de chunks completed válidos e regeneração de missing/invalid
- [x] 2.5 Testes: chunk IDs estáveis, limites de tamanho, manifest ordering, resume skip, fingerprint mismatch

## 3. LifecycleManager e workers (scaffolding)

- [x] 3.1 Criar `gpu/lifecycle.py` com lease único, spawn/join, timeout/kill, e verify-release pós-exit via guardian
- [x] 3.2 Definir contrato de job directory versionado sob `work/<book_id>/` (writes atômicos; inputs; pending chunks; config; exit codes: success / controlled_restart_needed / fatal); stdout/stderr só diagnóstico
- [x] 3.3 Scaffold entrypoint do Voice Design worker (load → job → unload best-effort → exit)
- [x] 3.4 Scaffold entrypoint do Fish Speech worker (load uma vez → loop chunks → persist → reclaim → monitor janela K/N → exit controlado)
- [x] 3.5 Testes com fake workers: lease impede dois ativos; ordem Voice Design → verify → Fish; restart sob exit controlado respeitando budget 3 e per-chunk 2 tentativas

## 4. Integrar Voice Design worker

- [x] 4.1 Mover geração batch (`ensure_voices_batch` / Parler) para execução via worker isolado orquestrado pelo LifecycleManager
- [x] 4.2 Orquestrador: após exit do Voice Design, verificar release antes de permitir fase Fish
- [x] 4.3 Garantir que o processo da CLI não mantém modelo Parler residente após a fase
- [x] 4.4 Atualizar testes de voice generation/pipeline para o novo caminho (fakes de worker ok)

## 5. Integrar Fish worker + speech chunking

- [x] 5.1 Converter diálogos interpretados em SpeechChunks e gravar pending no manifest antes da fase TTS
- [x] 5.2 Pipeline spawna Fish worker com chunks pendentes; worker persiste WAV por chunk antes de reclaim
- [x] 5.3 Implementar reclaim best-effort entre chunks + gate `before_chunk_target` / hard floor; progressive growth (K/N) → `controlled_restart_needed`; nunca esperar hard floor/OOM para provar degradação
- [x] 5.4 Orquestrador reinicia worker fresco (budget default 3 restarts; 2 tentativas/chunk) e continua pelo manifest; segunda falha no mesmo chunk id → abort com diagnóstico; OOM sem retry unbounded
- [x] 5.5 Merge lê ordem do manifest (não readdir); atualizar `audio/merge` / pipeline conforme necessário
- [x] 5.6 Remover/atualizar código e testes que exigem engine TTS quente entre todos os segmentos do capítulo sem possibilidade de restart

## 6. CLI, telemetria e docs

- [x] 6.1 Expor flags/env para hard floor, chunk target, load target (quando aplicável) e limite de chunk TTS; defaults só em config
- [x] 6.2 Progresso Rich/logging para spawn/exit de workers, verify release, skip/resume de chunks, e eventos `[gpu]` estruturados
- [x] 6.3 Atualizar `docs/SMOKE.md` / README: workers, resume, thresholds, critério de estabilidade do compositor
- [x] 6.4 Atualizar testes de CLI/handoff afetados pelas novas etapas de progresso

## 7. Smoke e calibração RX 7900 XTX

- [x] 7.1 Smoke: Voice Design worker → verify release → Fish worker com ≥5 SpeechChunks sequenciais, reclaim entre chunks, merge — **done** (`out/smoke_gpu_v3/smoke.m4b`, 41 chunks)
- [x] 7.2 Validar ausência de crescimento progressivo unbounded; hard floor não violado deliberadamente; Hyprland estável — **done with residual risk**: no progressive_growth; gates honor floor; mid-synth transient free dips to ~251 MiB (see `design.md`); compositor stayed up
- [x] 7.3 Validar resume: interromper/restart worker no meio; chunks completed não regenerados — **done** (interrupt after 2; mid-resume mtimes unchanged)
- [x] 7.4 Calibrar e registrar em `design.md`: `tts_max_chunk_chars=80`, reserve `1536`, `FISH_CHUNKS_PER_WORKER=2`, Parler `8192`, K/N `3/256`, Fish load `22528`
- [x] 7.5 Confirmar que OOM não é usado como controle normal; falhas reportam classificação correta — **done** on green path (0 `unexpected_oom`); OOM→`CONTROLLED_RESTART` without `failed_chunk_id`; residency `charged=False`
