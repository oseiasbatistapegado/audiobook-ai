## MODIFIED Requirements

### Requirement: Interpretar capítulos via Ollama com JSON validado
O sistema SHALL enviar o texto de cada capítulo a um backend LLM Ollama e SHALL aceitar apenas respostas JSON validadas por Pydantic (`LLMChapterResponse` ou equivalente). O LLM MUST NÃO retornar texto livre interpretável ad-hoc. O modelo MUST ser configurável via CLI (`--model`), com default definido em configuração central (`qwen3:8b` recomendado).

#### Scenario: Resposta JSON válida
- **WHEN** Ollama retorna JSON que passa na validação Pydantic
- **THEN** o sistema produz a lista de diálogos/segmentos tipados para o capítulo

#### Scenario: Resposta JSON inválida com retry
- **WHEN** a primeira resposta falha na validação Pydantic
- **THEN** o sistema registra o erro, solicita uma nova resposta incluindo o erro de schema, e tenta validar novamente

#### Scenario: Falha após retry
- **WHEN** a segunda resposta também é inválida
- **THEN** o sistema aborta o processamento do capítulo com erro contextual (capítulo, backend, motivo)

#### Scenario: Default Ollama é qwen3:8b
- **WHEN** o usuário executa `generate` sem `--model`
- **THEN** o backend LLM usa `qwen3:8b`
