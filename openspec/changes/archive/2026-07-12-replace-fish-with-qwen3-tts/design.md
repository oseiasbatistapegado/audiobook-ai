## Context

O pipeline atual separa Diretor (Qwen3:8B) → Voice Designer (Parler) → Ator TTS (Fish Speech) → SpeechChunks → M4B. Smoke validou `Qwen/Qwen3-TTS-12Hz-0.6B-Base` em Voice Clone com refs Parler (PT-BR aprovado, ~3 GB VRAM). O Fish está entrelaçado na orquestração (`run_fish_*`, backend id `fish-speech`, CLI `--fish-model`, specs `tts-fish-speech`) e o Parler pode depender transitivamente de DAC via `fish-speech`.

Spike de Emotion: a API `generate_voice_clone` do Base **não** expõe `instruct`/`emotion`/`style`/`prosody`. Instruction Control existe em CustomVoice/VoiceDesign, fora do escopo. O Base ainda pode inferir prosódia a partir do conteúdo textual (expressividade implícita).

## Goals / Non-Goals

**Goals:**

- Substituir Fish por Qwen3-TTS 0.6B Base como único ator TTS.
- Reutilizar refs Parler (`reference.wav` + `reference.txt`) sem regenerar personagens.
- Generalizar fase TTS (`run_tts_phase`, `run_tts_with_restarts`, id arquitetural `tts`).
- Parler autossuficiente sem `fish-speech`.
- Preservar Emotion no domínio/metadata; avaliar expressividade implícita via gate.
- Default chunk `500` e load target `6144 MiB`; calibrar chunks `500→1000→2000→4000` e load (peak+margem); lifecycle/resume intactos.

**Non-Goals:**

- Remover Parler; Voice Design / CustomVoice com Qwen3-TTS.
- Mapper `Emotion → instruct` ou hacks de sampling como “controle emocional”.
- Dual-backend / fallback Fish; CosyVoice.
- Alterar `VoiceProfile` ou prompt do diretor para descrições específicas do Qwen3-TTS.
- Mudar `VOICE_REF_MAX_SECONDS` nesta change.

## Decisions

### D1 — Único ator: Qwen3-TTS 0.6B Base

**Escolha:** `Qwen/Qwen3-TTS-12Hz-0.6B-Base`, modo Voice Clone, `language=portuguese` (ou equivalente suportado pela API pinada), logical id `qwen3-tts`, revision pinada no ModelManager.

**Alternativas:** Manter Fish; dual-backend; CustomVoice (quebra clone Parler). Rejeitadas — smoke já aprovou Base+Parler refs; rollback = Git.

### D2 — Superfície `TTSBackend` inalterada

**Escolha:** `Qwen3TTSBackend.synthesize(TTSRequest) → AudioSegment`; factory resolve só `qwen3-tts` (+ alias `qwen3tts`). Resolve voz via `resolve_voice_dir` → `reference.wav` / `reference.txt`.

**Alternativas:** Nova API pública TTS. Rejeitada — contrato estável.

### D3 — Emotion: metadata only + expressividade implícita

**Escolha:**

```text
Controle explícito Emotion → instruct     ❌ não suportado no Base
Expressividade implícita texto → prosódia ✅ esperada; medida por gate
```

- Preservar `emotion` em TTSRequest / SpeechChunks / manifest / saída do diretor.
- Backend **não** converte emotion em instruction; **não** inventa parâmetros; **não** trata `temperature`/sampling como controle emocional.
- Aceite de produto: fala com expressividade/prosódia naturais a partir do texto pt-BR — **não** “Emotion controla a geração”.

**Gate de expressividade implícita (obrigatório, não bloqueia integração técnica do backend):**

- Mesma voz/ref; textos pt-BR semanticamente distintos; sem `instruction`, tags Fish, ou hacks de sampling.
- Categorias: neutral, angry, sad, happy, fear, excited, whisper.
- Avaliar: naturalidade, entonação, energia, ritmo, prosódia, adequação ao conteúdo.
- **PASS** → documentar `Implicit Expressiveness Gate: PASS`; arquitetura permanece sem emotion control explícito.
- **FAIL** → documentar `Implicit Expressiveness Gate: FAIL`; **não** inventar emotion control; abrir `evaluate-qwen3-tts-explicit-emotion-control`.

**Alternativas:** CustomVoice/VoiceDesign; prefixar texto com tags Fish; usar temperature como proxy. Rejeitadas (escopo / inventar API / falso controle).

### D4 — Orquestração genérica `tts`

**Escolha:** Renomear `run_fish_phase` → `run_tts_phase`, `run_fish_with_restarts` → `run_tts_with_restarts`. Id de responsabilidade arquitetural: `tts`. Backend concreto / logical model: `qwen3-tts`. Configs de política OOM/residency: nomes neutros `TTS_*` (ex. `TTS_OOM_NO_PROGRESS_LIMIT`), não `FISH_*`.

**Alternativas:** Manter `run_fish_*` como dívida. Rejeitada — produto sem Fish não deve carregar nomenclatura Fish.

### D5 — Parler independente do Fish (DAC descoberto e pinado) + runtimes isolados

**Escolha:** Não assumir DAC transitivo via Fish. Procedimento obrigatório na implementação:

1. Ambiente de teste **sem** `fish-speech`.
2. Instalar extras de produto com **runtimes isolados** quando necessário.
3. Import + geração real Parler → identificar a dependência de decode efetivamente usada.
4. Declarar e pinar essa dependência no extra `voice-parler` / bootstrap Parler.
5. Registrar `DAC_PACKAGE` / `DAC_VERSION` no projeto (SMOKE/design notes da implementação).

**Conflito transformers (resolvido por isolamento):**

| Runtime | Interprete | transformers |
|---------|------------|--------------|
| Voice Design (Parler) | `.venv-parler` / `AUDIOBOOK_AI_VOICE_DESIGN_PYTHON` | `4.46.1` |
| TTS (Qwen3-TTS) | `.venv` / processo CLI | `4.57.3` |

Mesmo processo Python **não** consegue hospedar ambos. O orquestrador spawna cada worker no interprete adequado; a fronteira é o filesystem (`reference.wav` + `reference.txt`). `PYTHONPATH` do host/Nix é scrubbed no spawn (`gpu/runtimes.worker_env`).

**Gate de remoção do Fish / novo personagem:**

```text
fish-speech NÃO instalado
  + Parler (runtime isolado) gera reference.wav
  + Qwen3-TTS clona reference.wav
  = PASS  (NEW CHARACTER PIPELINE GATE)
```

**Alternativas:** Deixar DAC “acaso” via Fish; forçar um único transformers. Rejeitadas — bloqueia remoção limpa / quebra um dos motores.

### D6 — Chunking (default inicial + regra de escolha)

**Escolha:** Default inicial de produção `TTS_MAX_CHUNK_CHARS=500`. Não promover 1000/2000/4000 sem medição.

Calibração obrigatória sequencial `500 → 1000 → 2000 → 4000` com mesmas refs/textos/hardware/ROCm. Registrar por ponto: `chunk_chars`, `audio_duration_s`, `wall_time_s`, `RTF`, `peak_vram_mib`, success/failure, `quality_notes`, `prosody_notes`.

**Regra de escolha:** o default final é o **maior** chunk size que **não** apresente regressão perceptível de qualidade, prosódia ou estabilidade vs o último tamanho aprovado — não o maior que “cabe na VRAM”.

Resume: mudar o default altera `chunking_fingerprint`; manifests TTS anteriores incompatíveis regeneram a fase TTS.

**Alternativas:** Saltar para 2000 como default. Rejeitada — calibração incremental.

### D6b — `before_load_target_mib` inicial

**Escolha:** Default inicial **6144 MiB** para load da fase TTS (`tts` / `qwen3-tts`). O ~8 GiB legado do Fish NÃO é requisito permanente. Smoke observou ~3 GiB; 6144 é margem conservadora de integração, não afirmação de consumo.

Após pipeline estável, recalibrar: `target final = peak observado + margem operacional` (chunk size, duração, caches, allocator ROCm/PyTorch, first vs steady state).

### D7 — Voice refs

**Escolha:** Manter `VOICE_REF_MAX_SECONDS=6.0`. Refs existentes passaram no smoke. Recalibrar só com evidência.

### D8 — Remoção completa do Fish

**Escolha:** Após Qwen3-TTS estável no pipeline: remover `tts/fish_speech.py`, `workers/fish_speech.py`, `weights/fish.py`, extra `tts-fish`, `--fish-model`, aliases s1/s2, testes/docs Fish. Spec capability `tts-fish-speech` retirada; requisitos migram para `tts-qwen3`.

### D9 — Worker / lifecycle

**Escolha:** `workers/qwen3_tts.py` espelha garantias do Fish worker: SpeechChunks, persist-before-reclaim, guardian, controlled restart, resume, hard reclaim por exit. Baixa VRAM do Base **não** relaxa essas garantias. `expandable_segments` permanece no spawn do worker TTS.

### D10 — Follow-ups explícitos

Fora desta change:

- `evaluate-qwen3-tts-voice-design`
- `evaluate-qwen3-tts-explicit-emotion-control`

## Risks / Trade-offs

- [Regressão de atuação vs Fish `[emotion]`] → Mitigação: gate de expressividade implícita; follow-up se insuficiente; Emotion preservada no domínio.
- [Parler quebra sem Fish/DAC] → Mitigação: D5 + preflight antes de apagar Fish.
- [API/deps Qwen3-TTS vs ROCm] → Mitigação: pin de revision + smoke load no hardware oficial na Fase 1.
- [Rename amplo `fish` → `tts` quebra testes] → Mitigação: tasks de rename + suite GPU/lifecycle atualizada na mesma change.
- [Fingerprint/chunk default invalida resumes mid-flight] → Mitigação: documentar; usuários regeneram fase TTS.
- [Load target antigo 8 GiB oversized para ~3 GiB] → Mitigação: default inicial **6144 MiB**; recalibrar para peak + margem após smoke estável.

## Migration Plan

1. Infra: `weights/qwen3_tts.py`, ModelManager, extra runtime, pin revision, smoke load ROCm; default chunk 500 e load target 6144.
2. Backend + worker Qwen3-TTS; factory; wiring `run_tts_*`.
3. Spike DAC sem Fish → pinar no `voice-parler` + preflight; só então cortar Fish.
4. Corte Fish (código, deps, CLI, specs/docs/testes).
5. Pipeline PDF→M4B smoke (VRAM before/after load/gen/release).
6. Gate expressividade implícita (PASS/FAIL documentado) + calibração de chunks `500→4000` com regra de escolha; registrar defaults finais.
7. Rollback: `git revert` / checkout — sem fallback runtime.

## Open Questions

Nenhuma Open Question arquitetural bloqueante permanece.

| Item | Resolução |
|------|-----------|
| `TTS_MAX_CHUNK_CHARS` | Inicial **500**; benchmark `500→1000→2000→4000`; maior aprovado sem regressão vira default final (output da calibração). |
| `before_load_target_mib` | Inicial **6144 MiB**; recalibrar = peak real + margem (output da calibração). |
| Expressividade implícita | Gate obrigatório; PASS mantém arquitetura; FAIL abre follow-up — não inventa emotion control. |
| DAC do Parler | Descobrir sem Fish; declarar/pinar no `voice-parler`; registrar `DAC_PACKAGE`/`DAC_VERSION`. |

Valores finais de chunk, load target e resultado do gate são **outputs da implementação/calibração**, não pré-condições para aplicar a change.
