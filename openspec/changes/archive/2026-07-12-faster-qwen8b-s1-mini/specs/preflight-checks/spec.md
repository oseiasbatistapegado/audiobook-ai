## ADDED Requirements

### Requirement: Preflight valida o default qwen3:8b
Quando o usuário não sobrescreve `--model`, a checagem de preflight MUST exigir que `qwen3:8b` esteja disponível no host Ollama configurado (mesma regra de disponibilidade já usada para modelos nomeados).

#### Scenario: Default ausente no Ollama
- **WHEN** o preflight roda sem `--model` e `qwen3:8b` não está instalado
- **THEN** a CLI falha cedo sugerindo `ollama pull qwen3:8b`
