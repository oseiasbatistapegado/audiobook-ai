## ADDED Requirements

### Requirement: Capítulo só marca progresso após discovery + interpret
O progresso de interpretação book-scoped MUST considerar um capítulo concluído somente após Pass 1 (cast discovery) e Pass 2 (todas as unidades de interpretação) terem sucesso, com aplicação/persistência de story updates e merge de SpeechChunks no manifest quando aplicável. Falha em Pass 1 ou em qualquer unidade Pass 2 MUST NÃO marcar o `chapter_id` como interpretado.

#### Scenario: Falha na discovery não marca progresso
- **WHEN** Pass 1 falha após esgotar tentativas
- **THEN** o `chapter_id` NÃO entra no progresso persistido

#### Scenario: Falha numa unidade Pass 2 não marca progresso
- **WHEN** Pass 1 ok mas uma unidade Pass 2 falha
- **THEN** o `chapter_id` NÃO é tratado como interpretado no restart

## MODIFIED Requirements

### Requirement: Progress inválido por mudança de política ou modelo
O artefato de progresso MUST registrar identificadores de política/modelo usados (modelo Ollama + versões de política de adaptação/diarização). Quando o progresso gravado refere modelo ou versões de política diferentes da execução atual — incluindo bump que introduz two-pass cast-then-diarize — o sistema NÃO faz skip cego com base nesse progresso (reinterpreta ou invalida o progresso conforme política documentada).

#### Scenario: Progress inválido por mudança de política ou modelo
- **WHEN** o progresso gravado refere modelo ou versões de política diferentes da execução atual
- **THEN** o sistema NÃO faz skip cego com base nesse progresso (reinterpreta ou invalida o progresso conforme política documentada)

#### Scenario: Progress single-pass não pula após política two-pass
- **WHEN** o progresso foi gravado sob política de diarização anterior à two-pass e a execução atual usa a nova política
- **THEN** os capítulos NÃO são pulados com base nesse progresso antigo
