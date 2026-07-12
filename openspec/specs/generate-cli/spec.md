## Purpose

CLI Typer `audiobook-ai generate` que orquestra o pipeline completo do PDF ao audiolivro M4B sob `out/`.

## Requirements

### Requirement: Comando generate na CLI
O sistema SHALL expor uma CLI Typer com comando `generate` no formato `audiobook-ai generate <pdf> [--model ...] [--output ...]`, orquestrando o pipeline completo (extrair → parsear → interpretar → TTS → merge). Toda funcionalidade do MVP MUST ser acionável pela CLI. O default de saída MUST ser um audiolivro **M4B** sob `out/`.

#### Scenario: Geração bem-sucedida
- **WHEN** o usuário executa `audiobook-ai generate livro.pdf` (ou com `--output out/audiobook.m4b`) com Ollama, Fish Speech local e ffmpeg disponíveis
- **THEN** o sistema gera o arquivo M4B sob `out/` e encerra com código de sucesso

#### Scenario: PDF inexistente
- **WHEN** o caminho do PDF não existe
- **THEN** a CLI falha com erro claro e código de saída diferente de zero

### Requirement: Opções configuráveis principais
A CLI MUST permitir sobrescrever pelo menos: modelo Ollama (`--model`), arquivo de saída (`--output`), work-dir (`--work-dir`, default `out`), host Ollama via flags e/ou env, e SHALL permitir override do diretório de cache de pesos com prioridade `--cache-dir` > `AUDIOBOOK_AI_CACHE_DIR` > `~/.cache/audiobook-ai/`. A CLI MUST NÃO expor URL de servidor Fish Speech. A CLI SHALL permitir override dos thresholds de VRAM relevantes (reserve/hard floor, target antes de chunk, e quando aplicável target antes de load) e/ou limites de SpeechChunk via flags e/ou env, com defaults centralizados.

#### Scenario: Override de modelo Ollama
- **WHEN** o usuário passa `--model qwen3:8b`
- **THEN** o backend LLM usa `qwen3:8b` em vez do default configurado

#### Scenario: Work-dir default out/
- **WHEN** o usuário não passa `--work-dir`
- **THEN** o root de trabalho é `out/`, e artefatos resumíveis (story.json, manifest, áudios de chunk, logs) residem sob `out/<book_id>/`

#### Scenario: Sem URL Fish Speech
- **WHEN** o usuário consulta a ajuda da CLI `generate`
- **THEN** não há opção `--fish-speech-url` como caminho suportado

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
- **WHEN** `audiobook-ai generate` processa Voice Design e Fish Speech com Ollama
- **THEN** o usuário vê indicação de progresso relacionada a handoff/lifecycle/workers/chunks (além das etapas `interpret` / `tts` existentes)

#### Scenario: Resume visível
- **WHEN** a geração retoma com SpeechChunks já completed no manifest
- **THEN** a CLI indica skip/resume dos chunks existentes em vez de aparentar regenerar tudo em silêncio

### Requirement: Override opcional do teto de residency Fish
A CLI e/ou env MUST permitir override do teto opcional de chunks por invocação do worker Fish (`--fish-chunks-per-worker` e/ou `AUDIOBOOK_AI_FISH_CHUNKS_PER_WORKER`, ou equivalente documentado). Default MUST ser desabilitado (guardian-driven). Valor >0 reativa EXIT por contagem como escape hatch. A CLI MUST NÃO apresentar o teto como política primária de segurança de VRAM.

#### Scenario: Default guardian-driven sem teto
- **WHEN** o usuário executa `generate` sem override de teto de residency
- **THEN** o worker Fish não reinicia só por contagem fixa de chunks

#### Scenario: Escape hatch via flag/env
- **WHEN** o usuário define teto >0 via flag ou env suportada
- **THEN** o worker pode emitir restart com `restart_reason=residency` ao atingir esse teto

### Requirement: Default de --model na CLI é qwen3:8b
Quando `--model` é omitido, a CLI `generate` MUST usar o default centralizado `qwen3:8b` para o backend Ollama.

#### Scenario: Generate sem --model
- **WHEN** o usuário executa `audiobook-ai generate <pdf>` sem `--model`
- **THEN** o pipeline interpreta capítulos com `qwen3:8b`

### Requirement: Opção --fish-model para pesos Fish open
A CLI `generate` MUST expor `--fish-model` (e MAY aceitar env `AUDIOBOOK_AI_FISH_MODEL`) para selecionar um alias de pesos Fish **open** registrado no ModelManager. O default MUST ser `s1-mini`. Aliases MVP MUST incluir `s1-mini` e `s2-pro`. Valor desconhecido MUST falhar cedo com a lista dos aliases válidos. Esta opção MUST NÃO alterar o modelo Ollama (`--model`).

#### Scenario: Default fish-model é s1-mini
- **WHEN** o usuário executa `generate` sem `--fish-model` e sem env override
- **THEN** o pipeline assegura/carrega os pesos do alias `s1-mini`

#### Scenario: Override para s2-pro
- **WHEN** o usuário passa `--fish-model s2-pro`
- **THEN** o pipeline assegura/carrega os pesos do alias `s2-pro` e não o S1-mini

#### Scenario: Alias inválido
- **WHEN** o usuário passa `--fish-model` com um valor não registrado
- **THEN** a CLI falha cedo listando os aliases válidos (incluindo `s1-mini` e `s2-pro`)
