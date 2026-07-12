## Why

O pipeline MVP (PDF → Ollama → Fish Speech in-process → M4B) já está implementado e coberto por specs, mas ainda não é possível validar o produto de ponta a ponta: deps TTS frágeis, sem voz default, sem PDF de amostra, e falhas tardias quando faltam ffmpeg/Ollama. Esta change elimina esses bloqueios operacionais — sem novas features de produto.

## What Changes

- Documentar e endurecer o bootstrap do runtime TTS (`tts-fish` + `fish-speech`) até `import torch` / `import fish_speech` funcionar de forma reproduzível.
- Empacotar uma voz padrão (`narrator`) sob `assets/voices/` (ou equivalente) e fazer o `FishSpeechBackend` usá-la sem configuração manual.
- Validar (e documentar no smoke) o fluxo do `ModelManager`: 1ª execução baixa/cacheia; 2ª reutiliza sem re-download.
- Adicionar `samples/sample.pdf` e atualizar `docs/SMOKE.md` para um E2E reproduzível: `audiobook-ai generate samples/sample.pdf` → `out/sample.m4b` (ou path documentado equivalente).
- Na CLI `generate`, falhar cedo se faltarem `ffmpeg`, Ollama acessível, ou o modelo LLM configurado — com mensagens acionáveis.
- Sem EPUB, GUI, SFX, música, vozes avançadas multi-personagem, streaming ou API web.

## Capabilities

### New Capabilities

- `default-voice`: Voz padrão empacotada (`narrator`) e resolução automática pelo backend TTS para o smoke/MVP sem setup manual de referências.
- `preflight-checks`: Verificação antecipada de dependências externas (ffmpeg, Ollama, modelo LLM) antes de iniciar extração/TTS, com erros claros.

### Modified Capabilities

- `generate-cli`: Smoke E2E documentado e reproduzível; integração do preflight; progresso/erros alinhados ao bootstrap TTS e voz default.
- `tts-fish-speech`: Síntese MUST funcionar com a voz padrão empacotada quando o usuário não fornece `references/` próprias.

## Impact

- **Código**: `cli.py`, `pipeline.py`, `tts/fish_speech.py`, possivelmente `config.py` / novo helper de preflight; assets sob `assets/voices/`; fixtures em `samples/`.
- **Docs**: README + `docs/SMOKE.md` (install TTS, Ollama, smoke 1ª/2ª execução).
- **Deps**: endurecer documentação/pins do extra `tts-fish` e install `fish-speech` (sem mudar o modelo de produto in-process).
- **Não afeta**: EPUB, chunking de capítulos longos, memória narrativa rica, backends TTS adicionais.
