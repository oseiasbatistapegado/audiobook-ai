## MODIFIED Requirements

### Requirement: Verificar Ollama e modelo LLM antes do pipeline
Antes do trabalho pesado do pipeline, o sistema SHALL verificar que o host do
llama-server configurado está alcançável (via `GET /health` ou `GET /v1/models`) e
que o modelo LLM selecionado (`--model` ou default) está disponível no servidor.
Se a checagem falhar, MUST abortar com mensagem que indique correção (ex.: iniciar
`llama-server`, verificar `--model`).

#### Scenario: llama-server inacessível
- **WHEN** o host do llama-server não responde
- **THEN** a CLI falha cedo com erro contextual incluindo o host tentado

#### Scenario: Modelo LLM ausente
- **WHEN** llama-server responde mas o modelo configurado não está carregado
- **THEN** a CLI falha cedo sugerindo verificar o modelo carregado

### Requirement: Preflight valida o default qwen3:8b
Quando o usuário não sobrescreve `--model`, a checagem de preflight MUST exigir
que `qwen3:8b` esteja disponível no host do llama-server configurado (mesma regra
de disponibilidade já usada para modelos nomeados).

#### Scenario: Default ausente no llama-server
- **WHEN** o preflight roda sem `--model` e `qwen3:8b` não está carregado
- **THEN** a CLI falha cedo com instrução para iniciar o server com o modelo correto
