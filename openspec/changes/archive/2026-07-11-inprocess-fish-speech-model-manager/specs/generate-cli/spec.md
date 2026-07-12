## MODIFIED Requirements

### Requirement: Comando generate na CLI
O sistema SHALL expor uma CLI Typer com comando `generate` no formato `audiobook-ai generate <pdf> [--model ...] [--output ...]`, orquestrando o pipeline completo (extrair → parsear → interpretar → TTS → merge). Toda funcionalidade do fluxo MUST ser acionável pela CLI. O default de saída MUST ser um audiolivro **M4B** sob `out/`. A geração MUST NÃO exigir que o usuário inicie um servidor Fish Speech ou execute CLI/scripts externos de TTS.

#### Scenario: Geração bem-sucedida sem servidor TTS
- **WHEN** o usuário executa `audiobook-ai generate livro.pdf` com Ollama, deps TTS instaladas, GPU usável conforme política, ffmpeg e (na primeira vez) rede para download de pesos
- **THEN** o sistema assegura o modelo, gera o arquivo M4B sob `out/` e encerra com código de sucesso

#### Scenario: PDF inexistente
- **WHEN** o caminho do PDF não existe
- **THEN** a CLI falha com erro claro e código de saída diferente de zero

### Requirement: Opções configuráveis principais
A CLI MUST permitir sobrescrever pelo menos: modelo Ollama (`--model`), arquivo de saída (`--output`), work-dir (`--work-dir`, default `out`), host Ollama via flags e/ou env, e SHALL permitir override do diretório de cache de pesos com prioridade `--cache-dir` > `AUDIOBOOK_AI_CACHE_DIR` > `~/.cache/audiobook-ai/`. A CLI MUST NÃO expor URL de servidor Fish Speech.

#### Scenario: Override de modelo Ollama
- **WHEN** o usuário passa `--model qwen3:8b`
- **THEN** o backend LLM usa `qwen3:8b` em vez do default configurado

#### Scenario: Work-dir default out/
- **WHEN** o usuário não passa `--work-dir`
- **THEN** story.json, caches de LLM, áudios intermediários e logs em arquivo usam `out/` na raiz do projeto

#### Scenario: Sem URL Fish Speech
- **WHEN** o usuário consulta a ajuda da CLI `generate`
- **THEN** não há opção `--fish-speech-url` como caminho suportado

### Requirement: Progresso e logging via Rich/logging
A CLI MUST informar progresso ao usuário (Rich) e MUST usar logging (nunca `print`) com contexto de capítulo, etapa do pipeline, backend e tempo quando aplicável. Etapas de ensure/download/inicialização do modelo TTS MUST ser visíveis na primeira execução (e mensagem de modelo encontrado nas seguintes). Se logs forem escritos em arquivo, MUST residir sob `out/logs/` (ou `<work-dir>/logs/`).

#### Scenario: Feedback durante geração
- **WHEN** o pipeline processa múltiplos capítulos
- **THEN** o usuário vê indicação de progresso/etapa por capítulo sem uso de `print()`

#### Scenario: Primeira execução com download
- **WHEN** o modelo Fish Speech não está em cache e a geração inicia
- **THEN** a CLI indica download/inicialização do modelo (ex.: progresso) antes da síntese dos capítulos

#### Scenario: Segunda execução com cache
- **WHEN** o modelo já está em cache íntegro e a geração inicia
- **THEN** a CLI indica que o modelo foi encontrado/reutilizado e NÃO reinicia download completo
