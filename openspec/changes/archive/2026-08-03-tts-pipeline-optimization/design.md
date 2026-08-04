# Design: Otimização do Pipeline TTS

## Context

O pipeline atual opera de forma estritamente linear:
```
[LLM: Cap 1] → [TTS: Cap 1] → [LLM: Cap 2] → [TTS: Cap 2] → ...
```
Cada fase consome ~2h (LLM) + ~14min/capítulo (TTS) = ~16h total. A VRAM fica ~85% ociosa durante TTS, e o modelo Qwen3-TTS-0.6B consome ~2.8 GB com 24 GB disponíveis.

## Goals / Non-Goals

**Goals:**
- Reduzir tempo total de ~16h para ~8-10h (50-60% de economia)
- Manter resiliência: resume, retry, e diagnóstico de falha intactos
- Preservar determinismo: mesmo input → mesmo output (merge final)
- Escalabilidade: configuração por hardware (1-4 workers)

**Non-Goals:**
- Quantização do modelo (bitsandbytes não tem bom suporte ROCm; qwen_tts usa HuggingFace `device_map` + `bfloat16` nativo, sem ganho de speed com 8bit)
- Troca de modelo TTS (Qwen3-TTS-0.6B já é o mais leve disponível)
- GPU diferente (usuário tem RX 7900 XTX, bottleneck é throughput, não VRAM)

## Decisions

### D1: Multi-worker com N processos independentes

```
┌───────────────────────────────────────────────────────────┐
│                   ORCHESTRATOR                            │
│                                                           │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐    │
│  │ Worker TTS 0 │  │ Worker TTS 1 │  │ Worker TTS N │    │
│  │ (process A)  │  │ (process B)  │  │ (process N)  │    │
│  │ ┌──────────┐ │  │ ┌──────────┐ │  │ ┌──────────┐ │    │
│  │ │Qwen3-TTS │ │  │ │Qwen3-TTS │ │  │ │Qwen3-TTS │ │    │
│  │ │VRAMGuard │ │  │ │VRAMGuard │ │  │ │VRAMGuard │ │    │
│  │ └──────────┘ │  │ └──────────┘ │  │ └──────────┘ │    │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘    │
│         │                 │                 │             │
│         ▼                 ▼                 ▼             │
│   job_dir/            job_dir/            job_dir/        │
│   chunk 0,3,6,...    chunk 1,4,7,...    chunk 2,5,8,...  │
│                                                           │
│  Round-robin por voice_id → worker % N                    │
└───────────────────────────────────────────────────────────┘
```

**Racional:**
- Cada worker carrega o modelo uma vez e processa chunks em sequência (reusa engine)
- VRAM por worker = ~2.8 GB × N. Com 2 workers → 5.6 GB, ainda dentro dos 24 GB
- Com 4 workers → 11.2 GB, ainda seguro com 21 GB livres
- Round-robin por `voice_id` minimiza cache misses (mesma voz vai pro mesmo worker)
- Cada worker tem seu próprio `VRAMGuardian` — isolamento total de falhas
- Merge final lê o manifest consolidado (já existe, sem mudança)

**Alternativas consideradas:**
- *Batching intra-worker*: agrupar chunks da mesma voz em lotes maiores. Menos impacto porque o bottleneck é GPU inferência, não CPU preparation.
- *Distributed inference*: modelo particionado entre GPUs. Não se aplica (uma GPU).

### D2: Async pipeline com producer/consumer

```
┌─────────────────────────────────────────────────────────────┐
│                     ASYNC LOOP                              │
│                                                             │
│  Producer Thread                  Consumer Thread           │
│  (LLM interpret)                  (TTS workers)             │
│  ┌─────────────┐                  ┌──────────────┐          │
│  │ Cap N-1     │ ──queue──▶       │ Cap N-1      │          │
│  │ Cap N       │ ──queue──▶       │ Cap N        │          │
│  │ Cap N+1     │ ──queue──▶       │ Cap N+1      │          │
│  └─────────────┘                  └──────────────┘          │
│       ▶ Cap N+1                     ▶ Cap N+1               │
│                                                             │
│  Overlap: ~1 capítulo                                       │
│  Ganho: 2h × 0.75 = ~1.5h de economia                       │
└─────────────────────────────────────────────────────────────┘
```

**Racional:**
- Sobreposição de ~1 capítulo entre LLM e TTS gera ~1.5-2h de economia
- Thread producer enfileira capítulos interpretados; consumer thread consome da fila
- Queue size máxima = `TTS_ASYNC_OVERLAP` (default 1) para limitar memória
- Manifest escrito atomicamente por worker (`.tmp` + `rename`, já existente)
- Lock no manifest para escrita segura (file lock ou atomic rename)

**Alternativas consideradas:**
- *Thread-per-chapter*: muito overhead de criação/destruição. Workers residentes são melhores.
- *Full async (asyncio)*: o pipeline atual é sync/thread-based. Mudar para asyncio é risco alto.

### D3: VRAM tuning conservador

| Parámetro | Before | After | Racional |
|-----------|--------|-------|----------|
| `TTS_BEFORE_LOAD_TARGET_MIB` | 6144 | 3072 | Modelo consome 2.8 GB, 3 GB é margem operacional |
| `TTS_SAME_VOICE_BATCH_SIZE` | 4 | 8 | Mais batching sem risco de OOM |
| `before_chunk_target_mib` | 768 | 512 | Chunk é pequeno (~10 KB audio), não precisa de 768 MiB |

### D4: Job directory versionado para coordenação

- Cada worker escreve em seu próprio sub-dir `jobs/tts_worker_{i}/`
- Manifest consolidado em `manifest.json` com campo `worker_id` por chunk
- Merge final ignora `worker_id` e ordena por `chunk_order`
- Resume: worker detecta chunks já concluídos via manifest antes de iniciar

## Risks / Trade-offs

| Risk | Impact | Mitigation |
|------|--------|------------|
| Worker crash parcial | 1/N dos chunks perdidos | Resume lê manifest, worker fresco retoma |
| Race condition no manifest | Merge inconsistente | Atomic rename + lock por job dir |
| VRAM fragmentation com N workers | OOM em worker específico | `before_multi_worker_load_mib` = N × (per_worker + 200 MB margin) |
| Loss of determinism | Output diferente entre runs | Ordenação por chunk_id no merge (já existente) |
| Complexidade de debugging | Mais logs, mais fontes de erro | Log structured com worker_id, job_id |

## Migration Plan

Faseada e backward-compatible:

1. **Fase 0**: VRAM tuning (zero risco, apenas env vars)
2. **Fase 1**: Multi-worker (backward-compatible: `N=1` = comportamento atual)
3. **Fase 2**: Async pipeline (backward-compatible: `overlap=0` = linear)

Rollback: desligar feature via env var (`TTS_MULTI_WORKER_COUNT=1`, `TTS_ASYNC_OVERLAP=0`).

## Open Questions

1. **Quantos workers para 24 GB VRAM?** 2 workers é seguro (5.6 GB). 4 workers é agressivo (11.2 GB) — testar empiricamente.
2. **Round-robin por voice_id vs global?** Round-robin por voice_id minimiza cache misses no worker (mesma voz = mesmo worker). Round-robin global é mais balanceado mas pode dispersar a mesma voz entre workers.
3. **Async overlap ideal?** 1 capítulo é mínimo para ganho visível. 2+ capítulos pode aumentar uso de CPU/memória sem ganho proporcional.
