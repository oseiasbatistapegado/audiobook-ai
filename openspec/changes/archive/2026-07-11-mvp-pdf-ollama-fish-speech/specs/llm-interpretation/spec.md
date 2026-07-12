## ADDED Requirements

### Requirement: Interpretar capítulos via Ollama com JSON validado
O sistema SHALL enviar o texto de cada capítulo a um backend LLM Ollama e SHALL aceitar apenas respostas JSON validadas por Pydantic (`LLMChapterResponse` ou equivalente). O LLM MUST NÃO retornar texto livre interpretável ad-hoc. O modelo MUST ser configurável via CLI (`--model`), com default definido em configuração central (`qwen3.6:27b` recomendado).

#### Scenario: Resposta JSON válida
- **WHEN** Ollama retorna JSON que passa na validação Pydantic
- **THEN** o sistema produz a lista de diálogos/segmentos tipados para o capítulo

#### Scenario: Resposta JSON inválida com retry
- **WHEN** a primeira resposta falha na validação Pydantic
- **THEN** o sistema registra o erro, solicita uma nova resposta incluindo o erro de schema, e tenta validar novamente

#### Scenario: Falha após retry
- **WHEN** a segunda resposta também é inválida
- **THEN** o sistema aborta o processamento do capítulo com erro contextual (capítulo, backend, motivo)

### Requirement: Contrato mínimo de saída narrativa
Cada resposta válida MUST incluir diálogos/segmentos com speaker (id ou nome resolvível), emotion (enum fechado) e text. Atualizações de história (`story_updates`) MUST ser mínimas e opcionalmente vazias. Emoções MUST pertencer ao conjunto padronizado: `neutral`, `happy`, `sad`, `angry`, `fear`, `excited`, `whisper`.

#### Scenario: Diálogo com emoção válida
- **WHEN** o JSON contém um diálogo com emotion `angry` e texto não vazio
- **THEN** o modelo Pydantic aceita o diálogo

#### Scenario: Emoção fora do enum
- **WHEN** o JSON contém uma emotion não padronizada
- **THEN** a validação falha e o fluxo de retry/erro é acionado

### Requirement: Prompts externos ao código
Os prompts de interpretação MUST residir em arquivos sob `llm/prompts/` e MUST NÃO ser strings hardcoded no código de chamada ao LLM.

#### Scenario: Carregamento de prompt
- **WHEN** o backend interpreta um capítulo
- **THEN** o texto do prompt é lido do arquivo de prompts correspondente
