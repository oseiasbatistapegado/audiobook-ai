## ADDED Requirements

### Requirement: Descarregar modelo Ollama sob pedido do pipeline
O `OllamaBackend` SHALL expor uma operação de unload (ex.: `unload`) que solicita ao servidor Ollama a liberação do modelo configurado da memória/VRAM do host (ex.: `keep_alive=0` ou API de stop equivalente). A operação MUST ser segura para chamar quando o modelo já não está carregado (idempotente ou no-op sem falha fatal).

#### Scenario: Unload após interpretação
- **WHEN** o pipeline conclui `interpret_chapter` com chamada real ao Ollama e em seguida solicita unload
- **THEN** o backend solicita a liberação do modelo ao host Ollama configurado

#### Scenario: Unload com modelo já ausente
- **WHEN** unload é chamado e o modelo não está residente
- **THEN** o backend não aborta a geração por esse motivo

#### Scenario: Cache hit sem chamada Ollama
- **WHEN** `interpret_chapter` resolve por cache local sem chamar o servidor
- **THEN** o pipeline MAY omitir unload; se unload for chamado mesmo assim, MUST permanecer não-fatal
