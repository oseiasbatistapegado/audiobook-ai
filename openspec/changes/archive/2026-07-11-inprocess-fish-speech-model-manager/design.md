## Context

O pacote `audiobook_ai` já orquestra PDF → Ollama → TTS → M4B. O `FishSpeechBackend` atual é um cliente `httpx` contra `GET /v1/health` e `POST /v1/tts` em `http://127.0.0.1:8080`. Pesos, Python 3.12 e ROCm ficam fora do processo do app (clone/Docker). A proposta exige UX autocontida: download + inferência no mesmo processo, sem servidor HTTP.

Constraints do projeto: tipagem, Pydantic, interfaces pluggable, logging sem `print`, CLI Typer+Rich, artefatos sob `out/`, flake só com deps de sistema (ffmpeg, portaudio, etc.). Separação clara: LLM (Ollama) = diretor narrativo; Fish Speech = ator/voz.

## Goals / Non-Goals

**Goals:**

- Inferência Fish Speech **in-process** via APIs Python oficiais (`TTSInferenceEngine` e loaders associados).
- Pacote `weights/` (`manager.py`, `cache.py`, `fish.py`) para ensure/download/lock/validação/paths sob `~/.cache/audiobook-ai/`.
- Load único de pesos por execução de `generate`; reuso entre capítulos/segmentos.
- Progresso Rich na CLI para download e init; download automático na 1ª execução.
- Pin de `repository` + `revision` (tag/commit) — nunca `main`.
- Manter `TTSBackend` + factory extensível; LLM permanece Ollama (fora do processo TTS).

**Non-Goals:**

- Empacotar PyTorch/ROCm como derivação Nix completa no flake do app.
- Substituir Ollama por LLM in-process.
- Implementar Kokoro, XTTS, Piper ou Whisper backends.
- Clonagem ad-hoc de voz a partir de áudio do usuário (além de vozes/referências gerenciadas pelo manager).
- Servidor FastAPI/HTTP embutido, subprocess de `api_server`, cloud `api.fish.audio`, `git clone`/`wget`/`curl` para pesos.
- OCR / EPUB.

## Decisions

### D1 — Módulo `weights/` (fechado)

```text
src/audiobook_ai/weights/
  manager.py    # API ensure_model / get_model
  cache.py      # root resolution, layout, file lock
  fish.py       # FishSpeechModel: repository + revision + required files
```

- **Por quê:** `models/` reservado a domínio Pydantic; `weights/` = arquivos de IA.
- TTS continua em `tts/` (`base.py`, `fish_speech.py` no código atual — sem rename obrigatório neste change).

### D2 — Cache: prioridade e layout (fechado)

Prioridade de resolução do root:

1. CLI `--cache-dir`
2. Env `AUDIOBOOK_AI_CACHE_DIR`
3. Default `~/.cache/audiobook-ai/`

```text
~/.cache/audiobook-ai/
  fish-speech/
  # futuros: kokoro/, xtts/, …
```

Artefatos de **run** (`story.json`, chapters, logs, m4b) permanecem em `--work-dir` / `out/` — separados do cache de pesos.

### D3 — Download HF + validação resiliente (fechado)

- Somente API Python (`huggingface_hub`); **proibido** subprocess, CLI `hf`, `git clone`, `wget`, `curl`.
- Após download: validar **somente** os arquivos necessários à inicialização (lista em `FishSpeechModel` / registry).
- Validação resiliente a arquivos extras futuros no repo HF (ignorar o que não é required).
- Cache incompleto → reparo/re-download, nunca load parcial silencioso.
- Progresso via callback → Rich (sem `print`).

### D4 — Modelo versionado (fechado)

```python
FishSpeechModel(
    repository="fishaudio/…",   # id HF concreto no apply/spike
    revision="<tag-or-commit>", # nunca main / never floating
)
```

- Default de produto: qualidade S2 (VRAM documentada); override de id/revision via config permitido.
- Builds reproduzíveis: revision pinada no código/config versionada.

### D5 — Inferência in-process only (fechado)

```text
Application → FishSpeechBackend → Fish Speech Python API → GPU inference
```

- Load **uma vez** por instância/run; reuso em todos os segmentos.
- **Proibido:** HTTP, FastAPI, localhost, subprocess/CLI, processo externo Fish.
- Interface: `synthesize(TTSRequest) -> AudioSegment`.

### D6 — Vozes mínimas

- Pack/referência mínima (`narrator` + lista em config para `voice_map`).
- `voice_id` local estável em `story.json`; sem cloud.

### D7 — Spike de compatibilidade Python (fechado como processo)

Antes da implementação final do backend, spike DEVE validar:

- versão mínima de Python;
- deps necessárias e install via uv/pip;
- load do modelo + **uma** inferência simples;
- resultado → `requires-python`, extras (`tts-fish`), pins; evitar deps não usadas.

Sem segundo processo para contornar incompatibilidade de versão.

### D8 — Lock de download concorrente (fechado)

- File lock no diretório de cache do modelo.
- Dois processos `generate` simultâneos: só um baixa; o outro aguarda o lock e reutiliza o cache pronto.

### D9 — Separação LLM vs TTS (fechado)

- Ollama = interpretação narrativa (JSON).
- Fish Speech = síntese de voz apenas.
- Pipeline: PDF → Extract → LLM → Narrative JSON → TTS Backend → Audio → merge.

### D10 — GPU / CPU

- Preferir CUDA/ROCm; sem GPU usável → erro acionável. CPU não é default deste change.

### D11 — CLI / pipeline

- Remover `--fish-speech-url` / `FISH_SPEECH_URL`.
- Adicionar `--cache-dir` (prioridade D2).
- Stages: `model-ensure` / `model-download` / `model-init` + stages existentes.
- Mesma instância TTS ao longo dos capítulos.

### D12 — Testes e flake

- Unit: manager + lock com `tmp_path` / hub mock; backend com engine fake (sem torch no CI default).
- Smoke: 1ª execução (download) e 2ª (cache hit).
- Flake: manter ffmpeg/portaudio/sox; **não** empacotar PyTorch ROCm.

## Risks / Trade-offs

- **[Python app vs Fish]** → Spike obrigatório; ajustar `requires-python`/pins; bloquear se in-process for impossível sem subprocess.
- **[VRAM / S2]** → Documentar; permitir revision/modelo menor via config.
- **[API interna Fish instável]** → Adapter fino em `FishSpeechBackend` + pin de pacote.
- **[Download concorrente]** → File lock (D8); testar stale lock / crash mid-download.
- **[Repo HF muda layout]** → Validar só required files (D3); atualizar lista versionada se necessário.
- **[Nix + torch wheels]** → Wheels no venv; flake só libs sistema.

## Migration Plan

1. Spike (D7) → fechar pins.
2. `weights/` (cache, lock, fish model def, manager) + testes.
3. Reescrever `FishSpeechBackend` in-process; factory/pipeline/cli.
4. Remover HTTP TTS; atualizar testes + README/SMOKE.
5. Rollback: reverter change; servidor externo deixa de ser suportado.

## Open Questions

_(nenhuma pendente de produto — só outputs do spike/apply)_

1. ~~Cache root / prioridade~~ → D2.
2. ~~HTTP vs in-process~~ → D5.
3. ~~Nome do módulo~~ → D1 `weights/`.
4. ~~Concorrência download~~ → D8.
5. ~~Revision pinada / nunca main~~ → D4.
6. ~~Separação LLM/TTS~~ → D9.
7. **Spike apply:** valores concretos de `requires-python`, extra, `repository` + `revision` + required files (saída da task 1.x).
