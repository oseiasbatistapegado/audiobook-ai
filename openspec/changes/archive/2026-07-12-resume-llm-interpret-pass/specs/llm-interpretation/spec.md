## ADDED Requirements

### Requirement: Chave de cache LLM estável ao crescimento do story
A chave de cache de interpretação MUST NÃO hashear o dump completo volátil de `story_state` (voice_map, ordem de serialização, perfis completos). MUST incorporar, além de modelo, `chapter_id`, índice/hash da unidade e identificadores de política de adaptação/diarização, um fingerprint estável do elenco conhecido (ex.: ids de personagens e aliases canônicos ordenados). O payload enviado ao Ollama MAY continuar incluindo o `story_state` completo para qualidade de diarização.

#### Scenario: Restart com story já populado reutiliza cache da mesma unidade
- **WHEN** existe cache válido para modelo, unidade (mesmo texto), políticas e fingerprint de elenco equivalentes, e o `story.json` no disco tem mais campos voláteis (ex.: voice_map atualizado) sem mudar o fingerprint de elenco
- **THEN** `interpret_chapter` MAY reutilizar a entrada em cache sem nova chamada Ollama

#### Scenario: Novo personagem no elenco invalida fingerprint
- **WHEN** o fingerprint de elenco difere do usado ao gravar o cache (novo `character_id` ou aliases relevantes)
- **THEN** o sistema NÃO reutiliza essa entrada de cache

## MODIFIED Requirements

### Requirement: Cache LLM invalida ao mudar política de adaptação
A chave de cache de interpretação MUST incorporar um identificador estável da política de saída/adaptação (por exemplo locale `pt-BR` + versão de política, ou hash/versão do prompt de sistema), além de modelo, capítulo, unidade e fingerprint estável de elenco — e MUST NÃO depender do JSON completo de `story_state`. Alterar a política de adaptação MUST impedir hit em entradas de cache geradas sob política anterior.

#### Scenario: Cache miss após mudança de política
- **WHEN** existe cache válido para o mesmo modelo, capítulo/unidade e fingerprint de elenco sob uma política de adaptação anterior, e a política atual difere
- **THEN** `interpret_chapter` NÃO reutiliza essa entrada e solicita nova interpretação (ou equivalente sem hit)

#### Scenario: Cache hit com mesma política
- **WHEN** existe cache válido gerado com a mesma política de adaptação, modelo, capítulo/unidade e fingerprint de elenco
- **THEN** `interpret_chapter` MAY reutilizar a entrada em cache
