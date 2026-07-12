## MODIFIED Requirements

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

### Requirement: Feedback de handoff de VRAM na CLI
Quando o pipeline executar unload de Ollama, spawn/exit de workers GPU, verificação de release, restart controlado de worker, ou progresso por SpeechChunk/resume, a CLI `generate` SHALL refletir essas etapas no progresso Rich (e logging), de forma que o usuário consiga distinguir lifecycle/handoff de falha silenciosa.

#### Scenario: Progresso durante handoff e workers
- **WHEN** `audiobook-ai generate` processa Voice Design e Fish Speech com Ollama
- **THEN** o usuário vê indicação de progresso relacionada a handoff/lifecycle/workers/chunks (além das etapas `interpret` / `tts` existentes)

#### Scenario: Resume visível
- **WHEN** a geração retoma com SpeechChunks já completed no manifest
- **THEN** a CLI indica skip/resume dos chunks existentes em vez de aparentar regenerar tudo em silêncio
