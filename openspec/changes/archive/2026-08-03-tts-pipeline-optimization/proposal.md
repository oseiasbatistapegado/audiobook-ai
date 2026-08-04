# Proposal: Otimização do Pipeline TTS

## Why

A geração de audiobooks leva em média **16 horas** para livros de ~50 capítulos, com **~12 horas (75%)** gastas apenas na fase de TTS. A GPU (RX 7900 XTX, 24 GB) opera com VRAM subutilizada (~21 GB livres durante TTS, enquanto o modelo Qwen3-TTS-0.6B consome ~2.8 GB), indicando ociosidade crônica. Para escalar a livros maiores (100+ capítulos), é necessário reduzir o tempo da fase TTS em pelo menos 50%, sem comprometer a resiliência ou a reprodutibilidade do pipeline.

## What Changes

- **Multi-worker TTS**: N workers TTS (configurável, default 2) processam chunks em paralelo. Chunks são distribuídos por `voice_id` via round-robin, permitindo que o mesmo modelo carregado em cada worker sintetize simultaneamente.
- **Pipeline assíncrona (async pipeline)**: Thread producer executa a fase LLM (interpretando capítulo N+1) enquanto o consumer executa a fase TTS (sintetizando capítulo N), com sobreposição de ~1 capítulo.
- **VRAM tuning**: Reduz `TTS_BEFORE_LOAD_TARGET_MIB` de 6144→3072 MiB (consistente com consumo real de ~2.8 GB + margem) e aumenta `TTS_SAME_VOICE_BATCH_SIZE` de 4→8.
- **Configuração de escala**: Novas env vars `TTS_MULTI_WORKER_COUNT` (default 2), `TTS_ASYNC_OVERLAP` (default 1), `TTS_BEFORE_LOAD_TARGET_MIB` (default 3072), `TTS_SAME_VOICE_BATCH_SIZE` (default 8).

## Capabilities

### New Capabilities
- `multi-worker-tts`: Múltiplos processos worker TTS independentes, chunks distribuídos por voice_id round-robin, merge final a partir do manifest consolidado
- `async-pipeline`: Sobreposição de LLM (cap N+1) e TTS (cap N) via queue assíncrona com thread producer/consumer

### Modified Capabilities
- `tts-qwen3`: Adiciona suporte a batch size maior (8) e multiplexação por workers paralelos; requirement de "único backend por invocação" passa a permitir N instâncias simultâneas
- `vram-guardian`: New default de `before_load_target_mib` para TTS de 6144→3072 MiB; adiciona threshold `before_multi_worker_load_mib` para cálculo de headroom total (N workers × VRAM por worker)
- `gpu-lifecycle`: Lease passa a permitir N leases TTS simultâneos (não mais 1 exclusivo); adiciona coordenação entre workers via job directory versionado

## Impact

- **Code**: `lifecycle_manager.py` (multi-lease), `tts_backend.py` (batch aware de N workers), `orchestrator.py` (async loop + queue), `vram_guardian.py` (multi-worker headroom calc)
- **CLI/Env**: Novas flags/vars `--tts-multi-workers`, `--tts-async-overlap`, `--tts-before-load-target-mib`, `--tts-same-voice-batch-size`
- **Pipeline**: Ordem muda de linear → produtor/consumidor sobreposto; resume precisa considerar estado de ambos os lados
- **Dados**: Manifest precisa registrar worker_id por chunk para merge correto
- **Testes**: Novos testes de concorrência, merge multi-worker, e cenários de falha parcial
