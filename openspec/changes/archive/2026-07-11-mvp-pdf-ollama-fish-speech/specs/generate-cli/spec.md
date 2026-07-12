## ADDED Requirements

### Requirement: Comando generate na CLI
O sistema SHALL expor uma CLI Typer com comando `generate` no formato `audiobook-ai generate <pdf> [--model ...] [--output ...]`, orquestrando o pipeline completo (extrair → parsear → interpretar → TTS → merge). Toda funcionalidade do MVP MUST ser acionável pela CLI. O default de saída MUST ser um audiolivro **M4B** sob `out/`.

#### Scenario: Geração bem-sucedida
- **WHEN** o usuário executa `audiobook-ai generate livro.pdf` (ou com `--output out/audiobook.m4b`) com Ollama, Fish Speech local e ffmpeg disponíveis
- **THEN** o sistema gera o arquivo M4B sob `out/` e encerra com código de sucesso

#### Scenario: PDF inexistente
- **WHEN** o caminho do PDF não existe
- **THEN** a CLI falha com erro claro e código de saída diferente de zero

### Requirement: Opções configuráveis principais
A CLI MUST permitir sobrescrever pelo menos: modelo Ollama (`--model`), arquivo de saída (`--output`), work-dir (`--work-dir`, default `out`), e SHALL permitir host Ollama e URL Fish Speech local via flags e/ou env alinhados a `config.py`.

#### Scenario: Override de modelo
- **WHEN** o usuário passa `--model qwen3:8b`
- **THEN** o backend LLM usa `qwen3:8b` em vez do default `qwen3.6:27b`

#### Scenario: Work-dir default out/
- **WHEN** o usuário não passa `--work-dir`
- **THEN** story.json, caches, áudios intermediários e logs em arquivo usam `out/` na raiz do projeto

### Requirement: Progresso e logging via Rich/logging
A CLI MUST informar progresso ao usuário (Rich) e MUST usar logging (nunca `print`) com contexto de capítulo, etapa do pipeline, backend e tempo quando aplicável. Se logs forem escritos em arquivo, MUST residir sob `out/logs/` (ou `<work-dir>/logs/`).

#### Scenario: Feedback durante geração
- **WHEN** o pipeline processa múltiplos capítulos
- **THEN** o usuário vê indicação de progresso/etapa por capítulo sem uso de `print()`
