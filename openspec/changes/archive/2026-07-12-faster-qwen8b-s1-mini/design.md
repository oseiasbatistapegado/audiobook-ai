## Context

O pipeline local já orquestra Ollama → Voice Design → Fish Speech in-process (`fish-speech` 2.0) com ModelManager pinado em `fishaudio/s2-pro`. Na RX 7900 XTX o s2-pro ocupa ~19 GiB e força `TTS_MAX_CHUNK_CHARS=80`, com RTF ~13×; o LLM default `qwen3.6:27b` gasta vários minutos por capítulo curto. O usuário quer defaults `qwen3:8b` + OpenAudio S1-mini para throughput, **e** uma flag CLI para trocar entre pesos Fish open (como `--model` no Ollama).

O pacote `fish-speech==2.0.0` já carrega `model.pth` (além de safetensors) em `DualARTransformer.from_pretrained`. O repo S1-mini é **gated** (`fishaudio/openaudio-s1-mini` ≡ `fishaudio/s1-mini`).

## Goals / Non-Goals

**Goals:**

- Defaults: Ollama `qwen3:8b`, Fish alias `s1-mini`.
- CLI `--fish-model` / env `AUDIOBOOK_AI_FISH_MODEL` com aliases open registrados (`s1-mini`, `s2-pro`).
- Registry pinado por alias (repo, revision SHA, required files, cache dir lógico distinto).
- Presets de VRAM/chunk por alias quando o usuário não overrideou esses knobs.
- Docs + erro gated HF acionável; testes sem GPU.

**Non-Goals:**

- Modelos Fish **cloud-only** (s2.1-pro API, S1 full proprietário).
- Trocar o pacote `fish-speech` / HTTP server / API cloud.
- Auto-descoberta de qualquer repo HF arbitrário via string livre (só aliases do registry no MVP).
- Garantir qualidade idêntica 27b+s2-pro nos defaults novos.
- Recalibrar RTF empírico do volume Classroom (spike opcional).

## Decisions

### 1. LLM default → `qwen3:8b`

- **Escolha:** `DEFAULT_OLLAMA_MODEL = "qwen3:8b"`.
- **Por quê:** Já instalado; escape hatch `--model`.
- **Alternativas:** 4b / 35b-a3b — fora de escopo agora.

### 2. CLI `--fish-model` (espelho de `--model`)

- **Escolha:** flag `--fish-model` com choices/aliases do registry; default `s1-mini`; env `AUDIOBOOK_AI_FISH_MODEL`.
- **Valores MVP:** `s1-mini` | `s2-pro` (case-insensitive; rejeitar desconhecido com lista dos válidos).
- **Por quê:** Mesmo UX mental do Ollama; não mistura com `--model` (LLM).
- **Alternativas:** `--tts-model` (mais genérico, mas hoje só Fish); string HF livre — rejeitado no MVP.

### 3. Registry + cache por alias (não um logical id único)

| Alias | HF repo | Logical cache id | Layout |
|-------|---------|------------------|--------|
| `s1-mini` (default) | `fishaudio/openaudio-s1-mini` | `fish-s1-mini` | `model.pth`, `tokenizer.tiktoken`, … |
| `s2-pro` | `fishaudio/s2-pro` | `fish-s2-pro` | safetensors shards (definição atual) |

- `ModelManager.ensure_model(logical_id)` / `get_fish_definition(alias)` resolve a definição.
- Backend/worker recebe o path do alias escolhido (via job config / constructor).
- **Por quê:** Evita misturar arquivos s2+s1 no mesmo diretório; permite ter ambos em disco.
- **Alternativas:** um único dir `fish-speech` trocando arquivos — rejeitado.

### 4. Presets por alias (sem override explícito)

Defaults **globais** (produto) alinhados a `s1-mini`:

| Knob | Default produto (s1-mini) | Preset se `--fish-model s2-pro` e sem override |
|------|---------------------------|-----------------------------------------------|
| `FISH_BEFORE_LOAD_TARGET_MIB` | **8192** | **22528** |
| `TTS_MAX_CHUNK_CHARS` | **200** | **80** |

- Se o usuário passou `--tts-max-chunk-chars` / env de chunk ou override de fish load, **não** aplicar o preset do alias.
- **Por quê:** s2-pro sem chunk 80 OOMa no setup atual; s1-mini não precisa esvaziar a GPU.

### 5. Engine path inalterado

- Mesmo `TTSInferenceEngine` / `modded_dac_vq` para ambos os aliases.
- Spike na apply: load S1-mini + 1 frase; s2-pro já conhecido.

### 6. Docs / preflight

- Documentar o par `--model` (Ollama) + `--fish-model` (Fish open).
- Preflight Ollama valida o LLM selecionado.
- Download gated: mensagem com login HF + aceite S1-mini.

## Risks / Trade-offs

- **[Gated HF 401 no s1-mini]** → Mensagem acionável; `s2-pro` como fallback via flag.
- **[Incompat S1 vs fish-speech 2.0]** → Spike de load; bloquear merge se falhar.
- **[Usuário escolhe s2-pro sem baixar chunk]** → Presets automáticos mitigam; override explícito respeitado.
- **[Cache antigo `fish-speech/` orphan]** → Docs: pode apagar; novo layout usa `fish-s1-mini` / `fish-s2-pro`.
- **[Qualidade defaults]** → Aceito; flags revertem.

## Migration Plan

1. HF login + aceite S1-mini (se for usar o default).
2. Implementar registry + `--fish-model`; pinar SHAs.
3. `ollama pull qwen3:8b` se preciso.
4. Smoke: default s1-mini; smoke opcional `--fish-model s2-pro`.
5. Rollback: defaults antigos + só s2-pro no registry.

## Open Questions

- SHA S1-mini pinado na apply: `f4b445029346701e082b60bb63fcc2d1bb17a0e2` (via `model_info`; download ainda exige `hf auth login` + gated accept).
- Logical ids: `fish-s1-mini` / `fish-s2-pro` (cache antigo `fish-speech/` do s2-pro não é reutilizado automaticamente — re-download ou copiar manualmente).
- Spike load+síntese S1-mini na 7900: **bloqueado** sem token HF nesta sessão; repetir após `hf auth login`.
