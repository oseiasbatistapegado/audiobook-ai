## Context

O pipeline atual orquestra exclusão mútua por capítulo (release Fish → interpret Ollama → unload Ollama → Voice Design batch → load Fish → sintetizar diálogos → release Fish). Isso basta para caber um modelo por vez na RX 7900 XTX 24 GB, mas **não** resolve:

1. crescimento / pico de VRAM **entre segmentos** Fish Speech (OOM no segmento 1 após sucesso no 0);
2. `FishSpeechBackend.release()` in-process que **não** devolve VRAM de forma fiável no ROCm (spike: ~14.5 GiB torch_alloc após “release”; reclaim completo só com processo fresco);
3. ausência de resume de áudio — falha força regeneração de tudo (exceto cache LLM / vozes);
4. specs legadas que **exigem** manter o engine TTS quente entre todos os segmentos do capítulo.

Hardware alvo: AMD Radeon RX 7900 XTX, 24 GB, ROCm, Hyprland/Wayland (compositor compartilha a GPU). Estabilidade do desktop > throughput.

## Goals / Non-Goals

**Goals:**

- Orquestrador sem modelos GPU residentes; no máximo um modelo GPU **controlado pelo projeto** ativo por vez.
- Process isolation oficial: Voice Design e Fish Speech em workers; **exit do worker = hard reclaim**.
- Fish worker carrega uma vez, processa sequência limitada de `SpeechChunk`s, monitora VRAM; encerra controladamente se headroom degradar; orquestrador pode reiniciar worker e continuar via manifest.
- Unload/transição entre modelos só é “concluída” após verificação de VRAM (não após retorno de método Python).
- Três thresholds configuráveis: `hard_floor_mib`, `before_chunk_target_mib`, `before_load_target_mib` (por backend).
- Resume no nível de `SpeechChunk` (persistir + manifest).
- Supersede explícito das exigências de “engine sempre quente entre segmentos” quando conflitarem com segurança de VRAM.

**Non-Goals:**

- LLM semantic chunking (change separado).
- Throughput máximo / multi-GPU / paralelismo de modelos.
- Usar OOM como algoritmo primário de sizing.
- Garantir leituras byte-a-byte idênticas de VRAM após cada chunk (allocator caching).
- Qualidade pt-BR / unicidade do Voice Design; substituir Fish Speech ou Parler.
- Um processo por SpeechChunk.

## Decisions

### D1 — Orquestrador sem GPU; workers isolados

O processo da CLI/`run_generate` NÃO carrega Parler nem Fish Speech na GPU. Ele:

1. interpreta (Ollama — processo externo já existente);
2. spawna **Voice Design worker** → gera refs faltantes → exit;
3. verifica liberação de VRAM;
4. spawna **Fish Speech worker** → sintetiza SpeechChunks pendentes → exit (ou restart se degradação);
5. merge a partir dos WAVs persistidos.

**Alternativas consideradas:**

| Opção | Por quê não |
|-------|-------------|
| Soft reclaim in-process (`empty_cache`) | Spike mostrou leak até exit do processo |
| Subprocess só como fallback futuro | ROCm atual exige isolamento como estratégia oficial |
| Um processo por chunk | Custo de reload ~19 GiB por chunk; inaceitável |

### D2 — Worker Fish: load uma vez, N chunks, exit sob risco

Dentro do worker Fish:

```
load model (após before_load_target)
for chunk in pending:
  if free < before_chunk_target → reclaim best-effort → re-measure
  if free < hard_floor → controlled exit (não sintetiza)
  if progressive growth detected → controlled exit
  synthesize → persist WAV → update manifest → reclaim best-effort
exit  # hard reclaim
```

O orquestrador, ao ver exit controlado com chunks pendentes, spawna worker fresco e continua.

**Limites de restart (configuráveis):**

| Limite | Default | Notas |
|--------|---------|-------|
| Controlled Fish worker restarts / geração | **3** | Exclui o worker inicial |
| Tentativas do mesmo SpeechChunk | **2** total | 1ª falha + 1 retry; segunda falha no mesmo id → abort com diagnóstico |
| Unexpected OOM | sem retry unbounded | NÃO esgota budget em loop automático infinito |

Um restart por degradação de VRAM consome o budget de worker. Falha repetida no mesmo chunk é mais estrita que o budget global.

### D3 — Três thresholds (não dois)

| Knob | Default inicial | Papel |
|------|-----------------|-------|
| `hard_floor_mib` | 300 | Nunca iniciar trabalho GPU deliberadamente abaixo |
| `before_chunk_target_mib` | 768 | Headroom desejado antes do próximo chunk **com modelo residente** |
| `before_load_target_mib` | **por backend** (ver abaixo) | Seguro carregar o próximo modelo |

Defaults de load (conservadores, calibration-driven; NÃO universais):

| Backend | `before_load_target_mib` inicial |
|---------|----------------------------------|
| Fish Speech | **22528** (≈22 GiB free; derivado do spike 7900 XTX) |
| Parler Voice Design | valor **separado**, calibrado para Parler (NÃO herdar o do Fish) |
| Backend desconhecido | MUST NÃO herdar implicitamente o valor do Fish |

Defaults centralizados em `config.py`; CLI/env MAY sobrescrever com overrides **backend-specific**. MUST NÃO duplicar magic numbers nos backends.

MVP conservador: **não iniciar chunk abaixo de `before_chunk_target_mib`** após reclaim; se ainda abaixo do target mas ≥ floor, política default = treated as unsafe (abort/restart worker) até calibration provar o contrário.

### D4 — VRAMGuardian + LifecycleManager

```
gpu/
  memory.py      # snapshots (system free, torch alloc/reserved)
  guardian.py    # thresholds + decisões
  lifecycle.py   # lease único + spawn/join workers + verify release
```

- System-reported free VRAM é autoritativo para proteger o desktop.
- PyTorch allocated/reserved são telemetria / diagnóstico, não substitutos do free do sistema.
- `activate`/`run_phase` conceptual: assert lease livre → verify headroom → spawn worker → join → verify release → liberar lease.

### D5 — SpeechChunk como primitiva TTS (não LLM)

```python
@dataclass
class SpeechChunk:
    id: str              # estável / determinístico
    sequence: int
    text: str
    metadata: dict       # chapter_id, character_id, emotion, source dialogue refs, ...
```

Boundaries preferenciais: parágrafo → turno de diálogo → sentença → split por limite de chars.

Limites (`tts_max_chunk_chars`, opcionalmente sentences) configuráveis; default conservador calibrado no smoke 7900 XTX.

IDs e ordenação MUST ser determinísticos para o mesmo input + config (resume estável).

### D6 — Persist-before-reclaim + manifest resume + `book_id` namespace

`book_id` é o namespace estável de **todos** os artefatos resumíveis por livro. Derivação canônica: **BLAKE2b-128 do conteúdo do arquivo de input** (mesma regra já usada para character voices). Rename/move do source MUST NÃO criar nova identidade. O path do M4B de saída é controlado pelo usuário e MUST NÃO determinar `book_id`.

Layout canônico:

```
work/<book_id>/
  story.json
  manifest.json
  audio/
    chunk-000001.wav
    chunk-000002.wav
  logs/
```

Referências de voz permanecem no voice registry/cache book-scoped existente (fora deste tree se já for o caso).

- Escrever WAV → atualizar manifest → só então reclaim no worker.
- Restart: chunk válido no manifest → skip; missing/invalid → regenerate.
- Merge lê a ordem do manifest.
- Paths flat legados (`out/` sem `book_id`) MAY ser migrados ou suportados temporariamente; **novo** estado resumível MUST usar o layout book-scoped.

### D7 — Voice Design em worker dedicado (batch)

Mesma regra do produto atual (batch antes do TTS), mas o unload “real” é **exit do worker**, não só `unload()` in-process. O orquestrador MUST verificar VRAM antes de spawnar o Fish worker.

Se um personagem novo aparecer após entrar na fase Fish (não esperado se interpret do escopo estiver completo), o pipeline MUST checkpoint e agendar nova fase Voice Design — NÃO carregar Parler enquanto Fish está vivo.

### D8 — Supersede de specs legadas

Requisitos a **remover ou reescrever**:

- `vram-handoff`: “MUST NÃO liberar/recarregar o engine TTS entre segmentos consecutivos do mesmo capítulo” → substituído por política de SpeechChunks + worker residency limitada + restart sob degradação.
- `tts-fish-speech`: “MUST NÃO usar subprocess para síntese” e “engine MUST ser reutilizado para todos os synthesize sem release” → subprocess **é** o mecanismo oficial de isolamento; reuso do engine vale **dentro** de um worker para uma sequência limitada.

Handoff LLM↔TTS permanece: Ollama unloaded antes da fase Fish; nenhum worker GPU durante interpret remoto quando aplicável.

### D9 — Falha e telemetria

OOM NÃO é control flow normal. Unexpected OOM → parar fase GPU → persistir contexto → encerrar worker → reclaim → não retry infinito.

Erros MUST distinguir:

- modelo não cabe (`before_load` falhou);
- modelo cabe mas headroom de runtime insuficiente;
- memória não liberada entre workers/chunks (verify release falhou);
- crescimento progressivo detectado (restart worker).

Logs estruturados `[gpu]` com backend, event, chunk id, free/alloc/reserved, thresholds.

### D10 — IPC canônico: job directory

**Decisão:** job directory sob o work-dir é o IPC canônico.

- Cada worker recebe um path para a definição do job.
- Progresso durável passa por arquivos/manifest; stdout/stderr são só logs/diagnóstico (NÃO canal autoritativo de estado).
- Schema interno dos job files MAY evoluir, mas MUST ser **versionado** e escrito de forma **atômica**.
- Exit codes: `success` / `controlled_restart_needed` / `fatal`.
- Workers MUST NÃO spawnar outros workers GPU.

Rationale: debug/post-mortem, compatível com resume, sem acoplar estado a pipes, crash do worker não destrói o job, testes com fake workers mais simples.

### D11 — Heurística de crescimento progressivo (sliding window)

Detectar degradação **pós-reclaim sustentada**, não um único delta ruidoso.

Política inicial:

1. Após cada chunk bem-sucedido, registrar system free VRAM **depois** do reclaim.
2. Manter janela deslizante das últimas `K = 3` amostras pós-reclaim.
3. Disparar `controlled_restart_needed` quando free cair pelo menos `N = 256` MiB ao longo da janela **e** a tendência for monotonicamente / consistentemente descendente.
4. Restart imediato (independente da tendência) se o próximo chunk não satisfizer `before_chunk_target_mib`.
5. NUNCA esperar `hard_floor_mib` ou OOM para “provar” degradação.
6. Um único sample anômalo / ruído de allocator MUST NÃO sozinho disparar restart.

`K` e `N` MUST ser configuráveis e calibrados no smoke multi-chunk.

## Risks / Trade-offs

| Risk | Mitigation |
|------|------------|
| Overhead de reload Fish (~19 GiB) a cada restart de worker | Restart só sob degradação ou fim de fase; não por chunk |
| IPC / serialização frágil | Contrato mínimo + testes com fake workers; job files no work-dir |
| Medição de VRAM inconsistente no ROCm | Guardian abstrai provider; smoke calibra; free do sistema é autoritativo |
| Falsos positivos de “progressive growth” (allocator caching) | Janela K=3 + queda ≥N MiB com tendência; ignorar sample isolado; calibrar no smoke |
| Specs/testes antigos que exigem engine quente entre segmentos | Atualizar testes de handoff; documentar supersede |
| before_load_target alto demais bloqueia load legítimo | Calibrar por backend no smoke; defaults conservadores |
| Worker zombie retém VRAM | Lifecycle join com timeout + kill; verify release obrigatório |
| Resume com texto/chunking config mudada | Manifest MUST incluir fingerprint de config/chunking; mismatch invalida chunks |

## Migration Plan

1. **Primitives**: `SpeechChunk`, manifest, `VRAMGuardian` (fake providers), config dos três thresholds — sem mudar comportamento de saída ainda quando possível.
2. **Worker scaffolding**: entrypoints Voice Design / Fish com job I/O; LifecycleManager com lease.
3. **Wire Voice Design worker** no pipeline (substituir generate in-process na CLI).
4. **Wire Fish worker** + speech chunking + persist + resume.
5. **Supersede** código/testes alinhados às specs antigas de “no release entre segmentos”.
6. **CLI/env** knobs + telemetria Rich.
7. **Calibration smoke** na 7900 XTX: multi-chunk, restart de worker, verify release, Hyprland estável; tunar chunk size e `before_load_target`.

Rollback: flags/feature gate NÃO são obrigatórias se o change for atômico; em caso de regressão, reverter o change. Artefatos intermediários (manifest/audio) são aditivos ao work-dir.

## Open Questions

### Resolved

- **IPC:** job directory versionado/atômico sob work-dir; stdout/stderr só diagnóstico (D10).
- **`before_load_target_mib`:** backend-specific; Fish inicial **22528** MiB; Parler calibrado à parte; unknown NÃO herda Fish (D3).
- **Progressive growth:** sliding window K=3, queda ≥N=256 MiB com tendência descendente; gate imediato por `before_chunk_target`; sem esperar hard floor/OOM (D11).
- **Work-dir / `book_id`:** namespace `work/<book_id>/` via BLAKE2b-128 do conteúdo do input; output path do usuário não define identidade (D6).
- **Fish restart budget:** 3 controlled restarts/geração (além do inicial); 2 tentativas totais por SpeechChunk; OOM sem retry unbounded (D2).

### Still open (design)

Nenhum.

Valores finais de Parler `before_load_target_mib`, limites de tamanho de SpeechChunk, e calibração fina de K/N são **saídas empíricas do smoke** na RX 7900 XTX — não questões arquiteturais. Os defaults acima permitem implementação e MUST ser atualizados após o smoke multi-chunk.

### Calibration status (RX 7900 XTX smoke — 2026-07-12)

Evidence: `out/smoke_gpu_v3/smoke_report.json`, `vram_free_series*.txt`,
Fish `[gpu]` events; earlier `out/smoke_gpu/chunk_peak_calib/peak_by_chars.json`.

| Knob | Calibrated default | Evidence |
|------|-------------------|----------|
| `tts_max_chunk_chars` | **80** | Isolation peak calib: 120 chars + reserve 1536 → min free ≈301.5. Multi-chunk at 120 dipped to ~201 and hit HIP OOM. Full PDF smoke at **80** completed 41 chunks → merge (`smoke.m4b`); path had **0** `unexpected_oom`. |
| Parler `before_load_target_mib` | **8192** | Load gate passed with ~23 GiB free; release verified ~24 GiB. Keep separate from Fish. |
| Progressive growth K/N | **3 / 256** | No `progressive_growth` exits in successful smoke; residency soft-cap handles reclaim. |
| Fish `before_load_target_mib` | **22528** | Still appropriate; `wait_until_free` after worker/Ollama unload. Unchanged. |
| `hard_floor_mib` | **300** | Start-of-chunk gates honor floor. Mid-synth **transient** dips still occur (see residual risk). |
| `GPU_PROCESS_RESERVE_MIB` | **1536** | 1792/2560 made Fish OOM on ≤80-char chunks while system free ≫300 (fraction too tight). 1536 allows synth; peaks OOM the worker before starving amdgpu when over-budget. |
| `FISH_CHUNKS_PER_WORKER` | **2** | Soft residency → `restart_reason=residency` hard reclaim; **does not** consume `FISH_WORKER_RESTART_BUDGET`. |
| `FISH_WORKER_RESTART_BUDGET` | **8** | Counts OOM/headroom/progressive only. Residency restarts log `charged=False`. |

Also landed during smoke fix loop:

- Prefer `rocm-smi` over `torch.cuda.mem_get_info()` for authoritative system free.
- Poll `wait_until_free` after worker exit / Ollama unload before load gates.
- Fish release verify targets Fish load-target reclaim (not only hard floor).
- OOM `JobResult` MUST NOT set `failed_chunk_id` (retries gated by restart budget only).
- Orchestrator counts per-chunk attempts only on `FATAL` + `failed_chunk_id`.
- Smoke harness defaults `tts-max-chunk-chars` from `config.TTS_MAX_CHUNK_CHARS` (was hard-coded 500).

#### Residual risk (accepted)

Full smoke `out/smoke_gpu_v3`: **min_free ≈ 251.3 MiB** across ~8.4k samples; ~200 samples briefly &lt;300. Hyprland stayed up; no desktop kill; OOM was not used as normal control on the successful path. Raising process reserve further breaks Fish before it protects the floor. Prefer compositor stability over perfect free≥300 under mid-synth allocator peaks.
