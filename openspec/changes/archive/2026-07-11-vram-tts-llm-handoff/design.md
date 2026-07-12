## Context

No `run_generate`, o pipeline faz `tts_backend.ensure_ready()` (load completo do Fish Speech na GPU) **antes** do loop de capítulos. Em seguida, por capítulo: `interpret_chapter` (Ollama) → `synthesize` (Fish Speech).

Na RX 7900 XTX (~24 GB), Fish Speech reporta ~22.5 GB de VRAM. Quando Ollama carrega `qwen3.6:27b`, vê ~4 GiB livres e faz offload (~92% CPU / 8% GPU). Liberar só o TTS não basta se o modelo Ollama já estiver residente; o handoff precisa ser **bidirecional**.

Constraint: o loop por capítulo depende de `story` atualizado pelo interpret antes do TTS daquele capítulo — não dá para “todos os interprets depois todo o TTS” sem mudar a semântica narrativa (isso seria opção A / batch).

## Goals / Non-Goals

**Goals:**

- Exclusão mútua de VRAM entre fase LLM e fase TTS no pipeline `generate`.
- Fish Speech: unload do engine GPU + liberação efetiva de VRAM (PyTorch); pesos em disco intactos.
- Ollama: unload explícito do modelo após interpret (antes do TTS).
- Reuso do engine TTS entre segmentos consecutivos na mesma fase TTS (sem reload por diálogo).
- Progresso/logging das transições de handoff.
- Testes unitários com mocks (sem GPU real).

**Non-Goals:**

- Quantização / troca de modelo LLM ou TTS.
- Multiprocessamento / segundo processo só para TTS.
- Medição automática de VRAM livre como gate de produção (pode ser log diagnóstico opcional).
- Alterar ordem interpret↔TTS entre capítulos (story state continua sequencial).
- Suporte a múltiplos backends TTS além de Fish Speech neste change (API `release` no base pode ser no-op default).

## Decisions

### 1. Handoff por fase dentro do loop de capítulos (não batch global)

**Choice:** Antes de cada `interpret`: garantir TTS unloaded. Após interpret (antes do primeiro `synthesize` do capítulo): unload Ollama, depois `ensure_ready`/load TTS. Após o último segmento TTS do capítulo: unload TTS (pronto para o próximo interpret).

```
por capítulo:
  release_tts()
  interpret()
  unload_ollama()
  ensure_tts_loaded()
  synthesize × N
  release_tts()
```

**Why over batch-all-interprets-first:** Preserva dependência de `story_updates` entre capítulos.  
**Why over keep TTS loaded across chapters:** O próximo interpret precisa da VRAM livre; unload após TTS do capítulo é o ponto natural.

### 2. Separar “pesos em disco” de “engine na GPU”

**Choice:** Manter `ModelManager.ensure_model` cedo (cache/download + progresso `model-ensure`), mas **não** manter o engine residente até o primeiro TTS. Refatorar `ensure_ready` / init do pipeline:

- Fase precoce: `ensure_weights` (ou `ensure_ready` que só garante path + opcionalmente não carrega engine).
- Load do engine: sob demanda no início da fase TTS / `synthesize` se unloaded.

**Why:** Evita o bug atual (22 GB ocupados antes do interpret) sem perder feedback de download na primeira execução.

### 3. API `release()` no TTS (+ default no-op)

**Choice:** Adicionar `TTSBackend.release()` (ou `unload`) com default no-op na ABC; `FishSpeechBackend` implementa: drop refs do engine/queue, `gc.collect()`, `torch.cuda.empty_cache()` (quando CUDA/ROCm), `_loaded = False`.

**Why:** Pipeline orquestra sem acoplar a detalhes Fish Speech; testes injetam backend fake.

### 4. Unload Ollama via API do cliente (`keep_alive=0` / stop)

**Choice:** `OllamaBackend.unload()` (ou `release_model`) chama a API Ollama para descarregar o modelo atual (ex.: chat/generate com `keep_alive=0`, ou endpoint de stop equivalente na versão do cliente). Falha de unload: log warning + continua (TTS pode ainda falhar por OOM — melhor falhar no TTS com erro claro).

**Why:** Só liberar PyTorch não remove o processo `llama-server` do Ollama. Evidência no journal: Ollama já decide layout GPU no load; precisa unload para o próximo load caber na VRAM.

### 5. Eager weights, lazy engine; reload permitido após release

**Choice:** Atualizar a regra de “load único”: download/validação única por execução; engine GPU pode ser carregado N vezes após `release`. Entre `synthesize` consecutivos sem `release` no meio: sem reload.

**Why:** Spec atual proíbe reload entre capítulos; opção B exige o contrário entre fases.

### 6. Progress stages

**Choice:** Reusar `_notify` com stages como `vram-handoff` / detalhes `release-tts`, `unload-llm`, `load-tts` (nomes finais alinhados ao Rich existente). Logging estruturado com os mesmos termos.

**Why:** Operador precisa ver por que o pipeline “pausa” no reload (~30s no smoke atual).

## Risks / Trade-offs

- **[Risk] Reload Fish Speech por capítulo é lento (~tens de segundos)** → Mitigation: aceitar custo; futuro otimizar (manter engine se VRAM sobrar / flag); não reload entre segmentos do mesmo capítulo.
- **[Risk] `empty_cache` / drop de refs não libera VRAM (threads Fish Speech, fragmentação ROCm)** → Mitigation: teardown completo da queue/engine; spike rápido no apply; documentar se ROCm exigir workaround.
- **[Risk] `keep_alive=0` não descarrega a tempo / API muda** → Mitigation: encapsular em `OllamaBackend.unload`; verificar com `ollama ps` em smoke manual; retry curto opcional.
- **[Risk] Cache hit de LLM pula Ollama — unload desnecessário** → Mitigation: unload só se houve chamada real ao modelo neste capítulo (ou unload idempotente barato).
- **[Trade-off] Complexidade vs opção A (interpret tudo primeiro)** → Preferimos B para manter story sequencial sem redesign do estado.

## Migration Plan

- Change comportamental interno; CLI pública inalterada.
- Após merge: smoke `generate` em GPU 24 GB — confirmar `ollama ps` com alta fração GPU no interpret e Fish Speech com VRAM dominante só na fase TTS.
- Rollback: reverter change; comportamento volta ao eager load (offload CPU no LLM).

## Open Questions

- Nome exato da API: `release` vs `unload` (preferência: `release` no TTS, `unload` no Ollama — espelha ownership).
- Se unload Ollama em cache-hit deve ser no-op explícito (provável sim).
- Se vale flag CLI `--no-vram-handoff` para debug (default: handoff on). **Proposta: sem flag no MVP desta change** — sempre handoff quando backend é Fish Speech + Ollama.
