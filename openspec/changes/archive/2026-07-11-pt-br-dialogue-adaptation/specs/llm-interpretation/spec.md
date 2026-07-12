## ADDED Requirements

### Requirement: Texto falável em português brasileiro adaptado
O estágio de interpretação MUST produzir cada `dialogues[].text` em **português brasileiro** adequado a narração e fala em voz alta. O texto MUST ser uma **adaptação** do conteúdo do capítulo (qualquer idioma de origem), não uma tradução literal palavra a palavra: MUST preservar sentido, emoção e intenção, usando formulação natural em PT-BR. Nomes próprios e identificadores de personagem MUST permanecer estáveis quando forem identidades (salvo equivalente narrativo usual em PT-BR). Se o capítulo de origem já estiver em português brasileiro natural, o modelo MAY manter ou ajustar levemente o texto sem reescrita agressiva desnecessária. O sistema MUST NÃO introduzir um segundo passo LLM só para tradução/adaptação neste fluxo.

#### Scenario: Capítulo em idioma estrangeiro
- **WHEN** o backend interpreta um capítulo cujo texto de origem não está em português brasileiro
- **THEN** cada `dialogues[].text` na resposta validada está em português brasileiro adaptado (não calque literal) e permanece utilizável diretamente pelo TTS

#### Scenario: Capítulo já em PT-BR
- **WHEN** o backend interpreta um capítulo já escrito em português brasileiro natural
- **THEN** cada `dialogues[].text` permanece em português brasileiro natural, sem obrigação de reescrita substancial

#### Scenario: Sem passo extra de tradução
- **WHEN** o pipeline conclui `interpret_chapter` e segue para síntese TTS
- **THEN** o texto enviado ao TTS é o `dialogues[].text` da mesma resposta de interpretação (nenhuma segunda chamada LLM de tradução entre interpret e TTS)

### Requirement: Prompt declara política de adaptação PT-BR
O arquivo de prompt de interpretação sob `llm/prompts/` MUST instruir explicitamente a política de saída em português brasileiro adaptado (incluindo prosa de narrador e falas). A política MUST NÃO ficar apenas em comentários de código ou documentação externa ao prompt carregado.

#### Scenario: Prompt carrega regras de idioma
- **WHEN** o backend carrega o prompt de interpretação para uma chamada Ollama
- **THEN** o texto do prompt inclui a exigência de `dialogues[].text` em português brasileiro adaptado

### Requirement: Cache LLM invalida ao mudar política de adaptação
A chave de cache de interpretação MUST incorporar um identificador estável da política de saída/adaptação (por exemplo locale `pt-BR` + versão de política, ou hash/versão do prompt de sistema), além de modelo, capítulo e payload do usuário. Alterar a política de adaptação MUST impedir hit em entradas de cache geradas sob política anterior.

#### Scenario: Cache miss após mudança de política
- **WHEN** existe cache válido para o mesmo modelo, capítulo e payload sob uma política de adaptação anterior, e a política atual difere
- **THEN** `interpret_chapter` NÃO reutiliza essa entrada e solicita nova interpretação (ou equivalente sem hit)

#### Scenario: Cache hit com mesma política
- **WHEN** existe cache válido gerado com a mesma política de adaptação, modelo, capítulo e payload
- **THEN** `interpret_chapter` MAY reutilizar a entrada em cache
