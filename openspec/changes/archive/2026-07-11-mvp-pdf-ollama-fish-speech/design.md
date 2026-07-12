## Context

O repositório `narrative-compiler-py` tem dependências base (PyMuPDF, ollama, pydantic, typer, rich) e regras de arquitetura em `.cursor/rules/general.mdc`, mas ainda não há código de aplicação em `src/audiobook_ai/`. Este design define o MVP vertical: PDF → capítulos → JSON via Ollama → áudio Fish Speech → arquivo único.

**Constraints:** Python ≥3.14; tipagem completa; Pydantic para estruturas compartilhadas; interfaces desacopladas (`TextExtractor`, `LLMBackend`, `TTSBackend`); LLM só JSON validado; prompts em arquivos; estado único em `story.json`; logging (sem `print`); CLI Typer+Rich; **todo processamento TTS local** (sem Fish Audio cloud API).

## Goals / Non-Goals

**Goals:**

- Entregar um comando CLI que, dado um PDF, produz um audiolivro **M4B** (default) sob `out/`.
- Validar a estrutura modular `src/audiobook_ai/` com um único backend TTS (Fish-Audio S2 local) e um único backend LLM (Ollama).
- Manter estado mínimo de personagens/vozes para consistência entre capítulos.
- Deixar extensões futuras (outros TTS/LLM, EPUB) baratas via interfaces + factory.

**Non-Goals:**

- GUI / Web / Desktop / API HTTP do produto.
- EPUB, OCR, clonagem de voz ad-hoc no MVP, BGM, SFX, streaming, processamento distribuído.
- Implementações Kokoro / Piper / XTTS.
- Uso da **API cloud** Fish Audio (`api.fish.audio` ou equivalente).
- Grafo rico de cenas, relacionamentos ou timeline.
- Paralelismo de capítulos (apenas design que não impeça paralelismo futuro).
- Empacotar o modelo Fish Speech como derivação Nix completa (pesado / PyTorch ROCm fora do escopo do flake do app).

## Decisions

### D1 — Nome do projeto vs pacote

- **Decisão:** Manter `name = "narrative-compiler-py"` no `pyproject.toml`; pacote Python e entrypoint CLI usam `audiobook_ai` (ex.: script `audiobook-ai = "audiobook_ai.cli:app"`).
- **Por quê:** Alinha com as regras do projeto sem forçar rename do projeto git/PyPI neste MVP.
- **Alternativa:** Renomear o projeto para `audiobook-ai` — adiado para evitar churn desnecessário.

### D2 — Layout de módulos

```text
src/audiobook_ai/
  extractors/     # TextExtractor + PdfExtractor (PyMuPDF)
  parser/         # chapter split (TOC / heurísticas)
  llm/            # LLMBackend + OllamaBackend + prompts/
  state/          # load/save story.json, voice assignment
  tts/            # TTSBackend + FishSpeechBackend
  audio/          # merge/ffmpeg, AudioSegment I/O
  models/         # Pydantic: Book, Chapter, Character, Dialogue, StoryState, LLMResponse, AudioSegment
  utils/          # logging helpers, config
  config.py       # defaults centralizados
  pipeline.py     # orquestra Extract → Parse → Interpret → TTS → Merge
  cli.py          # Typer app
```

### D3 — Modelo Ollama padrão

- **Default recomendado:** `qwen3.6:27b` — melhor equilíbrio qualidade narrativa / tamanho entre os modelos listados pelo usuário; adequado para JSON estruturado de diálogos e emoções.
- **Alternativa leve documentada:** `qwen3:8b` para máquinas com menos VRAM.
- **CLI:** `--model` sobrescreve o default de `config.py`. Host Ollama configurável (`OLLAMA_HOST` / `--ollama-host`), default `http://localhost:11434`.
- **Não usar como default de interpretação narrativa:** modelos coder (`qwen2.5-coder:*`, `qwen3-coder:*`), embed (`nomic-embed-text`), nem Fast-Apply.

### D4 — Contrato LLM → JSON

O LLM retorna **apenas** JSON validado por Pydantic, por capítulo. Shape mínimo:

```text
LLMChapterResponse
  dialogues: list[Dialogue]   # speaker_id | speaker_name, emotion, text
  story_updates: StoryUpdates # characters novos/aliases mínimos (opcional vazio)
```

Emoções permitidas (enum fechado): `neutral`, `happy`, `sad`, `angry`, `fear`, `excited`, `whisper`.

Fluxo de validação: parse JSON → `model_validate` → se falhar, log + **um retry** com mensagem de erro de schema; se falhar de novo, abortar o capítulo com erro contextual (não interpretar texto livre).

Prompts em `llm/prompts/` (ex.: `interpret_chapter.md`), nunca inline no código.

### D5 — Estado mínimo (`story.json`) e diretório `out/`

```text
StoryState
  characters: list[Character]  # id permanente, name, aliases[]
  voice_map: dict[character_id, voice_id]  # voz fixa após primeira atribuição
```

- Sem scenes/relationships/timeline no MVP.
- Atribuição de voz: na primeira aparição do personagem, mapear para uma voz Fish Speech disponível (round-robin ou lista em `config.py`); nunca remapar dinamicamente.
- **Todos os artefatos do pipeline** ficam sob `out/` na raiz do projeto (gitignored):
  - `out/story.json`
  - `out/chapters/` (áudio intermediário por capítulo/segmento)
  - `out/cache/` (caches JSON do LLM, se houver)
  - `out/logs/` (se logs forem escritos em arquivo)
  - `out/<nome>.m4b` (audiolivro final; ou path sob `out/` via `--output`)
- Default de work-dir / output root: `out/` (equivalente a `--work-dir out`). Override via CLI permitido, mas o default documentado e preferido é `out/`.

### D6 — Extração e capítulos

- `PdfExtractor` (PyMuPDF) → texto por página + metadados TOC se existirem.
- `parser`: se TOC útil → capítulos por bookmarks; senão heurísticas (`Capítulo N`, `Chapter N`, headings de página, fallback “bloco por N páginas”).
- Saída: `Book` com `list[Chapter]` (id, title, text).

### D7 — Fish-Audio S2 local como único TTS MVP

Fonte oficial: [Installation](https://speech.fish.audio/install/), [Server](https://speech.fish.audio/server/), [Inference](https://speech.fish.audio/inference/).

#### Princípio: local only

- O MVP fala **somente** com um servidor Fish Speech **self-hosted** (HTTP local).
- **Proibido** no MVP: endpoint cloud Fish Audio, API keys de nuvem como caminho principal, ou upload de áudio para serviços remotos.
- O app `audiobook_ai` **não** embute o modelo; trata Fish Speech como processo/serviço externo atrás de `TTSBackend`.

#### Superfície que o projeto usa

| Peça | Detalhe |
|------|---------|
| Interface app | `TTSBackend.synthesize(request: TTSRequest) -> AudioSegment` |
| Implementação | `FishSpeechBackend` — cliente HTTP (`httpx`) para o servidor local |
| Health | `GET http://127.0.0.1:8080/v1/health` → `{"status":"ok"}` |
| Síntese | `POST /v1/tts` (payload conforme servidor local; voz via `reference_id` / referências salvas) |
| Config | `--fish-speech-url` / `FISH_SPEECH_URL`, default `http://127.0.0.1:8080` |
| Factory | `get_tts_backend("fish-speech")` — único backend registrado no MVP |

Cliente de referência upstream: `tools/api_client.py` (`--url .../v1/tts`, `--text`, `--reference_id`, `--output`). O contrato exato do JSON de `POST /v1/tts` deve ser confirmado contra a versão instalada (`/docs` no servidor); o backend isola essa adaptação.

#### Como subir Fish-Audio S2 (fora do pacote `audiobook_ai`)

1. **Clone** `https://github.com/fishaudio/fish-speech` (ambiente **separado** do venv do app — Fish Speech exige **Python 3.12**; o app usa ≥3.14).
2. **Deps de sistema (apt docs):** `portaudio19-dev`, `libsox-dev`, `ffmpeg` — no NixOS estas vão no `flake.nix` do projeto (ver D11).
3. **Install Python (upstream):** preferir `uv sync --python 3.12 --extra …` ou `pip install -e .[…]` / conda. Extras oficiais documentados: `cu126` / `cu128` / `cu129` (NVIDIA) ou `cpu`. **Neste host:** ROCm já está configurado no sistema; **não** usar extras CUDA. Opções ROCm alinhadas à doc:
   - **Preferida em NixOS+ROCm:** Docker oficial `compose.rocm.yml` (`docker compose -f compose.rocm.yml --profile server up --build`) — imagem baseada em `rocm/pytorch`, passa `/dev/kfd` e `/dev/dri`.
   - **Nativo:** instalar PyTorch ROCm no venv do fish-speech (índice ROCm / extras comunitários) e depois `pip install -e .` / `uv sync`; não há extra `rocm` estável listado na página de install “conda/uv” padrão — tratar como caminho avançado.
4. **Pesos:** `hf download fishaudio/s2-pro --local-dir checkpoints/s2-pro` (≥~24GB VRAM recomendados pela doc).
5. **API server local:**
   ```bash
   python tools/api_server.py \
     --llama-checkpoint-path checkpoints/s2-pro \
     --decoder-checkpoint-path checkpoints/s2-pro/codec.pth \
     --listen 0.0.0.0:8080
   ```
   Opções úteis: `--compile`, `--half`, `--api-key`, `--workers`.
6. **CLI inference** (alternativa / debug, não o caminho principal do app): pipeline DAC + text2semantic documentado em [Inference](https://speech.fish.audio/inference/).

#### Resolução de conflitos “docs vs local”

- A documentação mistura install local, Docker CUDA e Docker ROCm. **Decisão do projeto:** sempre self-hosted; em máquina AMD/ROCm, preferir `compose.rocm.yml` ou install nativo ROCm; nunca cloud API.
- `voice_map` do app mapeia `character_id` → `reference_id` (ou id de voz local pré-configurado no servidor), não para IDs de conta cloud.

### D8 — Merge de áudio (ffmpeg + M4B default)

- Segmentos por diálogo/capítulo → arquivos sob `out/chapters/` → **ffmpeg** concat → arquivo final.
- **Formato default: `.m4b`** (AAC em container M4B/audiobook). MP3 permanece suportado se o usuário passar `--output …/*.mp3`, mas **não** é o fallback primário nem o default da CLI.
- ffmpeg vem do **devShell Nix** (`flake.nix`); se ausente no PATH, erro claro na CLI.
- Formato inferido pela extensão de `--output`; default sugerido: `out/audiobook.m4b`.

### D9 — Pipeline e CLI

```text
audiobook-ai generate livro.pdf --model qwen3.6:27b
  [--output out/audiobook.m4b] [--work-dir out]
  [--ollama-host ...] [--fish-speech-url ...]
```

Defaults: `--work-dir out`, `--output` sob `out/` com extensão `.m4b` se omitido (definir na implementação em `config.py`).

`pipeline.run_generate(...)` é a API interna; CLI só parsing + Rich progress/logs. Cada etapa loga: capítulo atual, etapa, backend, tempo.

### D10 — Testes (MVP)

Prioridade: modelos Pydantic, parser de capítulos (fixtures texto), validação/retry LLM (mock), state voice_map, merge (mock ffmpeg ou fixture wav). Integração real Ollama/Fish Speech opcional/manual.

### D11 — NixOS / `flake.nix` (deps de sistema)

O ambiente de desenvolvimento é **NixOS** via `direnv` + `use flake`.

**No flake (devShell) — o que o Nix fornece:**

| Pacote Nix | Motivo |
|------------|--------|
| `ffmpeg` | Merge M4B/MP3 do pipeline |
| `portaudio` (+ headers via package) | Dep sistema Fish Speech (`portaudio19-dev`) |
| `sox` | Dep sistema Fish Speech (`libsox-dev`) |
| `pkg-config` | Build de bindings de áudio (pyaudio etc.) |
| `libsndfile` | I/O de áudio comum em stacks TTS |
| `cmake` | Builds nativos ocasionais de deps |
| python/uv/pip/… | Já presentes para o app |

**Fora do flake (documentado, não empacotado como derivação do modelo):**

- Repositório `fishaudio/fish-speech` (git clone) + `uv`/`pip` no Python 3.12 do Fish Speech.
- Pesos Hugging Face `fishaudio/s2-pro`.
- Drivers/runtime **ROCm** do host (já configurados no sistema; o flake do app não reinstala ROCm).
- Imagem/compose ROCm do Fish Speech, se o usuário escolher Docker.

ShellHook / direnv: após alterar `flake.nix`, rodar `direnv allow` (se necessário) e `direnv reload` na raiz do projeto.

## Risks / Trade-offs

- **[API Fish Speech instável / versão divergente]** → Isolar cliente HTTP atrás de `FishSpeechBackend`; validar contra `/v1/health` e `/docs` da versão instalada.
- **[Python 3.12 (Fish) vs ≥3.14 (app)]** → Processos separados; app só HTTP client.
- **[ROCm nativo vs Docker]** → Doc oficial de install “uv/conda” foca CUDA/CPU; ROCm está bem documentado via `compose.rocm.yml`. Preferir Docker ROCm se o install nativo falhar.
- **[VRAM ~24GB]** → Requisito da doc S2; máquinas menores podem precisar de modelo/quantização alternativa (fora do MVP).
- **[PDF sem texto / escaneado]** → OCR fora de escopo; falhar com mensagem clara.
- **[Heurística de capítulos fraca]** → Preferir TOC; fallback documentado.
- **[Modelo Ollama lento / VRAM]** → Default `qwen3.6:27b` com doc para `qwen3:8b`.
- **[JSON inválido recorrente]** → Retry único + prompt estrito.
- **[ffmpeg ausente]** → Check na partida do merge; flake deve fornecer no devShell.

## Migration Plan

- Greenfield: criar pacote e entrypoint; nenhuma migração de dados.
- Rollback: remover change / não publicar entrypoint; sem DB.
- Após apply: usuário precisa de Ollama + modelo puxado, servidor Fish-Audio S2 local (ou compose ROCm), e `nix develop`/`direnv` com ffmpeg.

## Open Questions

_(nenhuma — decisões fechadas pelo usuário)_

1. ~~Endpoint Fish Speech~~ → **Fechado:** servidor local `tools/api_server.py`, health `/v1/health`, TTS `POST /v1/tts`, default `http://127.0.0.1:8080`; detalhe do payload fino na implementação contra a build instalada.
2. ~~Formato de saída default~~ → **Fechado:** **M4B** como default; MP3 só se explicitamente pedido.
3. ~~Onde gravar `story.json`~~ → **Fechado:** tudo sob **`out/`** na raiz do projeto.
