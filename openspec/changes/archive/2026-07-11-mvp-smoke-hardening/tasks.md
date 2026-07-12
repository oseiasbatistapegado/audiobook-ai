## 1. Bootstrap TTS e documentação

- [x] 1.1 Revisar/atualizar README com a sequência mínima de install (`uv sync --extra tts-fish`, fish-speech pinado) e o critério `python -c "import torch; import fish_speech"`
- [x] 1.2 Validar no ambiente do projeto que os imports TTS funcionam após os passos documentados (ajustar pins/docs se falhar)
- [x] 1.3 Documentar no README/SMOKE pré-requisitos Ollama + GPU/ffmpeg (direnv)

## 2. Voz padrão empacotada

- [x] 2.1 Criar `assets/voices/narrator/` com `reference.wav` + `reference.lab` (clipe curto, licença OK)
- [x] 2.2 Implementar resolução de path dos assets (pacote/projeto) e wiring no `FishSpeechBackend` (prioridade: inject → assets → `./references/`)
- [x] 2.3 Fallback de `voice_id` desconhecido para `narrator` com log de warning
- [x] 2.4 Testes unitários: assets existem; resolução de path; fallback; override do usuário

## 3. Preflight de dependências

- [x] 3.1 Implementar módulo/funções de preflight: ffmpeg no PATH, Ollama alcançável, modelo LLM presente, imports `torch`/`fish_speech`
- [x] 3.2 Integrar preflight no início de `generate` / `run_generate` (falha cedo, mensagens acionáveis, sem download de pesos se imports falharem)
- [x] 3.3 Testes com mocks: ffmpeg ausente, Ollama down, modelo ausente, fish_speech ausente

## 4. Sample PDF e smoke docs

- [x] 4.1 Adicionar `samples/sample.pdf` curto com texto selecionável
- [x] 4.2 Atualizar `docs/SMOKE.md` com install, Ollama, comando `audiobook-ai generate samples/sample.pdf --output out/sample.m4b`, 1ª/2ª execução de pesos e artefatos esperados
- [x] 4.3 Alinhar default/`--output` documentado para o critério `out/sample.m4b`

## 5. Validação ModelManager + E2E

- [ ] 5.1 Confirmar via smoke/manual que 1ª execução baixa/cacheia e 2ª indica cache hit sem re-download completo
- [x] 5.2 Rodar `uv run pytest` e corrigir regressões
- [ ] 5.3 Executar smoke E2E manual até produzir `out/sample.m4b` (GPU + Ollama + ffmpeg)
