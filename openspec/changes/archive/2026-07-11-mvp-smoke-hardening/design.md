## Context

O pacote `audiobook_ai` já orquestra PDF → Ollama → Fish Speech in-process → M4B. Specs e código do MVP e do ModelManager estão arquivados, mas o ambiente atual não fecha o smoke: extra `tts-fish`/pacote `fish-speech` não instalados de forma confiável, sem voz default empacotada, sem `samples/sample.pdf`, e falhas de ffmpeg/Ollama só aparecem no meio do pipeline.

Constraints: tipagem, Pydantic, logging sem `print`, interfaces pluggable, artefatos sob `out/`, pesos em `~/.cache/audiobook-ai/` (ou override), flake só com deps de sistema (ffmpeg etc.), sem HTTP TTS, sem cloud Fish Audio.

## Goals / Non-Goals

**Goals:**

- Tornar o bootstrap TTS reproduzível (`import torch` + `import fish_speech`).
- Entregar voz `narrator` empacotada e usada automaticamente no smoke.
- Documentar e validar 1ª/2ª execução do `ModelManager` (download vs cache hit).
- Smoke E2E: `samples/sample.pdf` → `out/sample.m4b` via `audiobook-ai generate`.
- Preflight na CLI: ffmpeg, Ollama reachable, modelo LLM presente — falha cedo com correção explícita.

**Non-Goals:**

- EPUB, GUI, SFX, música, streaming, API web.
- Chunking de capítulos longos / memória narrativa rica.
- Múltiplas vozes avançadas ou clonagem ad-hoc pelo usuário.
- Empacotar PyTorch/ROCm no flake Nix.
- Mudar o contrato `TTSBackend.synthesize(TTSRequest) -> AudioSegment`.

## Decisions

### D1 — Assets de voz no repo (`assets/voices/`)

```text
assets/voices/narrator/
  reference.wav   # áudio curto de referência (licença OK / gerado para o projeto)
  reference.lab   # transcript alinhado ao wav (formato Fish Speech)
```

- O backend resolve a voz default apontando o loader de referências do Fish Speech para esse diretório (via `references_dir` / cwd bridge já existente, ou symlink/copia lógica para o layout `references/<id>/` esperado pelo upstream).
- **Por quê:** o usuário não precisa montar `references/` manualmente para o smoke.
- **Alternativa:** baixar vozes do HF no `ModelManager` — adiado (mais complexidade; smoke precisa offline após install).

### D2 — Resolução de voz no `FishSpeechBackend`

Prioridade:

1. `references_dir` explícito (teste/injeção).
2. `assets/voices/` empacotado (path relativo ao pacote ou raiz do projeto documentada).
3. `./references/` no cwd (override do usuário), se existir.

- `voice_id` default / primeiro no `voice_map`: `narrator`.
- Se `voice_id` não tiver pasta correspondente, fallback para `narrator` com log de warning (MVP smoke), sem inventar vozes.

### D3 — Bootstrap TTS (docs + validação, não “magic install” na CLI)

- README + SMOKE documentam a sequência exata (`uv sync --extra tts-fish`, `uv pip install --no-deps fish-speech@…`).
- Adicionar um check de import no preflight TTS (ou comando/doc de validação): se `torch`/`fish_speech` ausentes, erro com a sequência de install — a CLI **não** baixa o pacote Python automaticamente.
- Critério de aceite: `python -c "import torch; import fish_speech"` no venv do projeto.

### D4 — Preflight antes do pipeline pesado

Ordem na `generate` / início de `run_generate`:

1. PDF existe (já existe).
2. `ffmpeg` no PATH.
3. Ollama: host alcançável (ex. tags/list ou ping leve da API).
4. Modelo LLM (`--model`) presente na lista do Ollama.
5. Imports TTS (`torch`, `fish_speech`) quando o backend for Fish Speech.
6. Então: extract → … → `model-ensure` / TTS.

Mensagens MUST citar o remédio (direnv/ffmpeg, `ollama pull …`, `uv sync --extra tts-fish`, …).

### D5 — Sample PDF e output do smoke

- `samples/sample.pdf`: PDF curto com texto selecionável (1–2 páginas, idealmente com heading de capítulo simples).
- Comando canônico:
  ```bash
  audiobook-ai generate samples/sample.pdf --output out/sample.m4b
  ```
  (ou default documentado que produza `out/sample.m4b` — preferir `--output` explícito no SMOKE para não ambiguidade com `audiobook.m4b`).
- SMOKE cobre: install, Ollama, 1ª execução (download pesos), 2ª (cache hit), artefatos esperados.

### D6 — ModelManager: validação via smoke, sem redesign

- Nenhuma mudança de contrato do manager; apenas garantir que o smoke exercita ensure + cache hit e que erros de import/GPU continuam claros.
- Progresso Rich já existente permanece.

### D7 — Testes

- Unit: resolução de path da voz default; preflight com mocks (ffmpeg missing, Ollama down, model missing).
- TTS: synthesize com engine fake + assets path real (existência dos arquivos).
- Não exigir GPU no CI default; smoke GPU permanece manual em `docs/SMOKE.md`.

## Risks / Trade-offs

- **[Licença/tamanho do WAV de referência]** → Usar clipe curto gerado/licenciável; não commit de modelos grandes.
- **[Layout Fish Speech `references/<id>/`]** → Adapter no backend; testar contra `v2.0.0-beta`.
- **[Preflight Ollama falso-negativo (API lenta)]** → Timeout curto + mensagem clara; não bloquear com retry infinito.
- **[Install fish-speech `--no-deps` frágil]** → Documentar pins do spike; se quebrar, atualizar README nesta change (não expandir para Nix torch).
- **[Sample PDF binário no git]** → Aceitável se pequeno; gerar via script só se necessário.

## Migration Plan

1. Adicionar assets + sample PDF + preflight + wiring de voz.
2. Atualizar README/SMOKE.
3. Rodar unit tests; smoke manual GPU.
4. Rollback: reverter change; comportamento anterior (voz opcional / falha tardia) volta.

## Open Questions

_(nenhuma bloqueante — defaults abaixo)_

1. Output do smoke → **Fechado:** `out/sample.m4b` via `--output` no SMOKE.
2. Fallback de voice_id desconhecido → **Fechado:** `narrator` + warning (D2).
