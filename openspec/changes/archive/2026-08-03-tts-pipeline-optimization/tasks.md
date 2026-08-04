# Tasks: Otimização do Pipeline TTS

## 1. Config VRAM tuning (zero risco)

- [x] 1.1 Alterar `TTS_BEFORE_LOAD_TARGET_MIB` de 6144 para 3072 em `src/audiobook_ai/config.py:49`
- [x] 1.2 Alterar `BEFORE_CHUNK_TARGET_MIB` de 768 para 512 em `src/audiobook_ai/config.py:45`
- [x] 1.3 Alterar `TTS_SAME_VOICE_BATCH_SIZE` de 4 para 8 em `src/audiobook_ai/config.py:80`
- [x] 1.4 Adicionar constantes de config para multi-worker: `TTS_MULTI_WORKER_COUNT` (default 2, max 4), `TTS_ASYNC_OVERLAP` (default 1, max 3) em `src/audiobook_ai/config.py`
- [x] 1.5 Atualizar testes relacionados a VRAM thresholds em `tests/test_gpu_lifecycle.py` e `tests/test_interpret_progress.py`
- [x] 1.6 Rodar `uv run pytest` para verificar que mudanças de config não quebram nada

## 2. Manifest: campo worker_id

- [x] 2.1 Adicionar `worker_id: int | None = None` ao `ManifestChunkEntry` em `src/audiobook_ai/state/manifest.py:24`
- [x] 2.2 Adicionar `worker_id: int | None` ao parâmetro de `mark_completed` em `src/audiobook_ai/state/manifest.py:105`
- [x] 2.3 Atualizar chamadas de `mark_completed` para passar worker_id (`qwen3_tts.py:318`)
- [x] 2.4 Adicionar teste para `worker_id` serializado/deserializado no manifest

## 3. Multi-worker: distribuidor de chunks

- [x] 3.1 Criar função `distribute_chunks_by_voice_round_robin(chunks, worker_count)` em `src/audiobook_ai/gpu/orchestrate.py:680` que calcula `voice_id % worker_count`
- [x] 3.2 Criar função `resolve_tts_workers(book, worker_count)` que: (a) carrega manifest, (b) filtra chunks pending, (c) distribui por worker_id
- [x] 3.3 Escrever testes unitários para `distribute_chunks_by_voice_round_robin` com 2, 3, 4 workers

## 4. Multi-worker: lifecycle manager

- [x] 4.1 Criar classe/método `LifecycleManager.spawn_multi_workers(...)` que: (a) calcula `before_multi_worker_load_mib` = N × (2800 + 200), (b) spawna N processos worker independentes, (c) retorna lista de PIDs/worker_ids
- [x] 4.2 Criar método `LifecycleManager.join_multi_workers(worker_ids, timeout_s=3600)` que aguarda todos workers terminarem
- [x] 4.3 Cada worker recebe seu `JobDefinition` com `pending_chunk_ids` subset e `worker_id`
- [x] 4.4 Adicionar `MultiWorkerError` exception para quando um lease multi já está ativo
- [x] 4.5 Garantir que `run_worker` (single) e `spawn_multi_workers` (multi) são mutuamente exclusivos

## 5. Multi-worker: TTS worker subprocess

- [x] 5.1 Atualizar `src/audiobook_ai/workers/qwen3_tts.py` para: (a) ler `worker_id` do job, (b) usar `worker_id` no path de output (via `pending_chunk_ids` subset), (c) atualizar manifest com worker_id por chunk
- [x] 5.2 Garantir que o worker usa seu próprio `VRAMGuardian` instance (não shared) — `g = VRAMGuardian(SystemMemoryProvider(), cfg=cfg)` na linha 124
- [x] 5.3 Worker lê job config para `before_load_target_mib` por-worker (não o total do sistema) — linha 107-110
- [x] 5.4 Worker emite logs com `worker_id` no prefixo: `WorkerPrefixAdapter` → `[gpu] worker=N ...` — linhas 89-91

## 6. Multi-worker: orchestrate phase

- [x] 6.1 Adicionar parâmetros `tts_multi_workers: int | None` e `tts_same_voice_batch_size: int | None` a `run_tts_phase` em `src/audiobook_ai/gpu/orchestrate.py:267`
- [x] 6.2 Se `tts_multi_workers > 1`: usar `spawn_multi_workers` com distribuição round-robin — linhas 313-443 de `orchestrate.py`: resolve chunks via `resolve_tts_workers()`, build `JobDefinition` per-worker, spawn via `lifecycle.spawn_multi_workers()`, join via `lifecycle.join_multi_workers()`, verify manifest clean
- [x] 6.3 Se `tts_multi_workers == 1`: comportamento atual (single worker) — linha 445+ fallback para loop original
- [x] 6.4 Adicionar fallback: se VRAM < multi-worker threshold, reduzir para 1 worker com warning — linhas 316-330: try `guardian.require_safe_headroom`, except → `multi_workers = 1`
- [x] 6.5 CLI: adicionar flag `--tts-multi-workers` em `src/audiobook_ai/cli.py:144`
- [x] 6.6 CLI: adicionar flag `--tts-async-overlap` em `src/audiobook_ai/cli.py:155`

## 7. Async pipeline: queue e threads

- [x] 7.1 Criar módulo `src/audiobook_ai/pipeline/async_loop.py` com:
  - Classe `AsyncPipeline` que orquestra producer/consumer
  - `ProducerThread`: executa LLM interpret para cap N+1, enfileira no queue
  - `ConsumerThread`: executa TTS para cap N, consome do queue
  - Queue com `maxsize = TTS_ASYNC_OVERLAP`
- [x] 7.2 Producer usa `LLMBackend.interpret_chapter()` existente (não precisa mudar)
- [x] 7.3 Consumer chama `run_tts_phase()` com os chunks do capítulo consumido
- [x] 7.4 Adicionar `stop_event` para graceful shutdown (SIGINT)

## 8. Async pipeline: orchestration integration

- [x] 8.1 Modificar `pipeline.py` para suportar modo assíncrono:
  ```
  if async_overlap > 0:
      run_async_pipeline(...)
  else:
      run_linear_pipeline(...)
  ```
- [x] 8.2 Fase 1 (pré-processamento): LLM interpreta TODOS os capítulos
- [x] 8.3 Fase 2 (async): TTS cap N enquanto LLM cap N+1
- [x] 8.4 Fase 3 (cleanup): TTS finaliza capítulos restantes
- [x] 8.5 CLI: adicionar flag `--tts-async-overlap` em `src/audiobook_ai/cli.py` (concluído em 6.6)

## 9. Async pipeline: resume state

- [x] 9.1 Estender `interpret_progress.json` para registrar: (a) capítulos interpretados, (b) capítulos sintetizados
- [x] 9.2 `AsyncPipeline` verifica resume state antes de iniciar
- [x] 9.3 Se TTS já completou cap N, producer pula cap N+1
- [x] 9.4 Se LLM ainda processando cap N, consumer aguarda

## 10. Telemetria e logging

- [x] 10.1 Todos os logs de TTS incluir `worker_id` quando multi-worker — `WorkerPrefixAdapter` no worker, logs de spawn/join com worker_id em lifecycle.py
- [x] 10.2 Adicionar log de progresso agregado a cada N chunks: "progress: M/N (w0: A, w1: B)"
- [x] 10.3 Adicionar métrica de throughput: chunks/hora por worker
- [x] 10.4 Adicionar `progress_callback` stage "async-pipeline" com detail "overlap=N"

## 11. Testes

- [x] 11.1 Teste: `distribute_chunks_by_voice_round_robin` com 100 chunks, 4 workers
- [x] 11.2 Teste: `spawn_multi_workers` com 2 workers injetados (mock)
- [x] 11.3 Teste: merge final ordena chunks por `sequence` ignorando `worker_id`
- [x] 11.4 Teste: async pipeline com 1 worker (linear) — comportamento idêntico ao atual
- [x] 11.5 Teste: async pipeline com 2 workers — chunks distribuídos corretamente
- [x] 11.6 Teste: resume após crash de worker individual
- [x] 11.7 Teste: graceful shutdown com Ctrl+C (signal SIGINT)
- [x] 11.8 Teste: fallback VRAM (reduz de 2→1 worker)
- [x] 11.9 `uv run pytest` passa com todos os testes novos (45/45, 307/308 suite total)
- [x] 11.10 `uv run ruff check` e `uv run pyright` passam

## 12. Documentação

- [x] 12.1 Atualizar `.envrc` com novas variáveis de ambiente documentadas
- [x] 12.2 Adicionar `--help` no CLI para novas flags (typer gera automaticamente)
- [x] 12.3 Atualizar `AGENTS.md` com novos parâmetros de configuração
