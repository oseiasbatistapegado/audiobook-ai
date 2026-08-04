## Purpose

CLI Typer `audiobook-ai generate` que orquestra o pipeline completo do PDF ao audiolivro M4B sob `out/`.

## Requirements

### Requirement: Comando generate na CLI
O sistema SHALL expor uma CLI Typer com comando `generate` no formato `audiobook-ai generate <pdf> [--model ...] [--output ...]`, orquestrando o pipeline completo (extrair → parsear → interpretar → TTS → merge). Toda funcionalidade do MVP MUST ser acionável pela CLI. O default de saída MUST ser um audiolivro **M4B** sob `out/`.

#### Scenario: Geração bem-sucedida
- **WHEN** o usuário executa `audiobook-ai generate livro.pdf` (ou com `--output out/audiobook.m4b`) com Ollama, Qwen3-TTS local e ffmpeg disponíveis
- **THEN** o sistema gera o arquivo M4B sob `out/` e encerra com código de sucesso

#### Scenario: PDF inexistente
- **WHEN** o caminho do PDF não existe
- **THEN** a CLI falha com erro claro e código de saída diferente de zero

### Requirement: Opções configuráveis principais
A CLI MUST permitir sobrescrever pelo menos: modelo Ollama (`--model`), arquivo de saída (`--output`), work-dir (`--work-dir`, default `out`), host Ollama via flags e/ou env, e SHALL permitir override do diretório de cache de pesos com prioridade `--cache-dir` > `AUDIOBOOK_AI_CACHE_DIR` > `~/.cache/audiobook-ai/`. A CLI MUST NÃO expor URL de servidor TTS nem opções Fish Speech. A CLI SHALL permitir override dos thresholds de VRAM relevantes (reserve/hard floor, target antes de chunk, e quando aplicável target antes de load) e/ou limites de SpeechChunk via flags e/ou env, com defaults centralizados.

#### Scenario: Override de modelo Ollama
- **WHEN** o usuário passa `--model qwen3:8b`
- **THEN** o backend LLM usa `qwen3:8b` em vez do default configurado

#### Scenario: Work-dir default out/
- **WHEN** o usuário não passa `--work-dir`
- **THEN** o root de trabalho é `out/`, e artefatos resumíveis (story.json, manifest, áudios de chunk, logs) residem sob `out/<book_id>/`

#### Scenario: Sem URL / opções Fish
- **WHEN** o usuário consulta a ajuda da CLI `generate`
- **THEN** não há `--fish-speech-url`, `--fish-model`, nem flags `FISH_*` como caminho suportado

#### Scenario: Override de reserve de VRAM
- **WHEN** o usuário passa flag ou env de reserve/hard floor de VRAM
- **THEN** o guardian usa o valor informado nas decisões de segurança

### Requirement: Progresso e logging via Rich/logging
A CLI MUST informar progresso ao usuário (Rich) e MUST usar logging (nunca `print`) com contexto de capítulo, etapa do pipeline, backend e tempo quando aplicável. Se logs forem escritos em arquivo, MUST residir sob `out/logs/` (ou `<work-dir>/logs/`).

#### Scenario: Feedback durante geração
- **WHEN** o pipeline processa múltiplos capítulos
- **THEN** o usuário vê indicação de progresso/etapa por capítulo sem uso de `print()`

### Requirement: Feedback de handoff de VRAM na CLI
Quando o pipeline executar unload de Ollama, spawn/exit de workers GPU, verificação de release, restart controlado de worker, ou progresso por SpeechChunk/resume, a CLI `generate` SHALL refletir essas etapas no progresso Rich (e logging), de forma que o usuário consiga distinguir lifecycle/handoff de falha silenciosa.

#### Scenario: Progresso durante handoff e workers
- **WHEN** `audiobook-ai generate` processa Voice Design e TTS com Ollama
- **THEN** o usuário vê indicação de progresso relacionada a handoff/lifecycle/workers/chunks

#### Scenario: Resume visível
- **WHEN** a geração retoma com SpeechChunks já completed no manifest
- **THEN** a CLI indica skip/resume dos chunks existentes em vez de aparentar regenerar tudo em silêncio

### Requirement: Override opcional do teto de residency TTS
A CLI e/ou env MUST permitir override do teto opcional de chunks por invocação do worker TTS (`--tts-chunks-per-worker` e/ou `AUDIOBOOK_AI_TTS_CHUNKS_PER_WORKER`, ou equivalente documentado). Default MUST ser desabilitado (guardian-driven). Valor >0 reativa EXIT por contagem como escape hatch. A CLI MUST NÃO apresentar o teto como política primária de segurança de VRAM. Flags/env `FISH_CHUNKS_PER_WORKER` MUST NÃO permanecer como interface de produto.

#### Scenario: Default guardian-driven sem teto
- **WHEN** o usuário executa `generate` sem override de teto de residency
- **THEN** o worker TTS não reinicia só por contagem fixa de chunks

#### Scenario: Escape hatch via flag/env
- **WHEN** o usuário define teto >0 via flag ou env suportada
- **THEN** o worker pode emitir restart com `restart_reason=residency` ao atingir esse teto

### Requirement: Default de --model na CLI é qwen3:8b
Quando `--model` é omitido, a CLI `generate` MUST usar o default centralizado `qwen3:8b` para o backend Ollama.

#### Scenario: Generate sem --model
- **WHEN** o usuário executa `audiobook-ai generate <pdf>` sem `--model`
- **THEN** o pipeline interpreta capítulos com `qwen3:8b`

### Requirement: Default de chunk TTS documentado como 5000
A CLI/documentação de `generate` MUST refletir o default de produto `TTS_MAX_CHUNK_CHARS=5000` e continuar permitindo override via flag/env existente. MUST NÃO apresentar a escada de calibração `500→4000` como passo obrigatório.

#### Scenario: Help/defaults mencionam 5000
- **WHEN** o usuário consulta help/docs do limite de chunk TTS
- **THEN** o default indicado é 5000 (salvo override)
