## Purpose

Persistência e resolução de vozes geradas/atribuídas (cache registry) com precedência sobre assets empacotados e validação de idioma pt-BR.

## Requirements

### Requirement: Persistência de vozes no cache
O sistema SHALL persistir cada voz gerada sob `voices/<book_id>/<character_id>/` (default sob o cache root do app) contendo no mínimo `metadata.json`, `reference.wav` e texto alinhado (`reference.txt` ou `reference.lab`). O registry MUST sobreviver a reinício. Metadata MUST incluir `language=pt-BR`, `generator`, `generator_version`, `model_id`, `seed`, snapshot do `voice_profile` quando houver, e `book_id`/`character_id`.

#### Scenario: Cache sobrevive restart
- **WHEN** uma voz é materializada no registry do livro e a aplicação reinicia
- **THEN** a resolução do mesmo `book_id`/`character_id` reutiliza os arquivos em disco sem regenerar

#### Scenario: Metadata audita proveniência generativa
- **WHEN** uma voz é persistida pelo fluxo automático
- **THEN** `metadata.json` inclui language pt-BR, model_id, generator, seed e perfil usado

### Requirement: Persistido vence reatribuição futura
Se o registry já contém uma voz válida pt-BR gerada para o par `book_id`/`character_id`, o sistema MUST reutilizá-la e MUST NÃO regenerar só porque o algoritmo ou versão do modelo mudou, salvo pedido explícito de regeneração pelo usuário.

#### Scenario: Pasta existente bloqueia regeneração
- **WHEN** `voices/<book_id>/<character_id>/` já existe com wav + metadata pt-BR válidos
- **THEN** ensure/get retorna essa voz sem sobrescrever `reference.wav`

### Requirement: Lookup e materialização idempotente
`VoiceRegistry` MUST oferecer ensure/get scoped por `book_id` que, se a pasta válida existir, retorna sem sobrescrever; se não existir, materializa a partir do `GeneratedVoice` do Voice Design.

#### Scenario: Ensure não sobrescreve voz válida
- **WHEN** `ensure` é chamado para um character já materializado no book
- **THEN** os arquivos existentes permanecem inalterados

#### Scenario: Ensure materializa ausente
- **WHEN** `ensure` é chamado para character ausente e o gerador produziu ref válida
- **THEN** o registry cria a pasta sob `voices/<book_id>/<character_id>/`

### Requirement: Precedência de resolução de referência
A resolução de diretório de voz para o TTS MUST respeitar: (1) override do usuário `./references/<voice_id>/`, (2) registry `voices/<book_id>/<character_id>/`, (3) somente então qualquer asset empacotado explicitamente permitido para override/dev — assets de banco NÃO satisfazem geração automática de personagem. Refs automáticas MUST ser pt-BR geradas.

#### Scenario: Override do usuário vence cache
- **WHEN** existem `./references/carlos/` e cache do livro para carlos
- **THEN** a síntese usa o override do usuário

#### Scenario: Registry do livro vence asset empacotado
- **WHEN** o registry do `book_id` possui voz válida e também existe asset empacotado com id semelhante
- **THEN** a síntese usa a voz do registry do livro

### Requirement: Proibição de voz de idioma inválido no registry automático
O registry MUST NÃO aceitar materialização automática com language diferente de `pt-BR`, nem stock/share como sucesso.

#### Scenario: Rejeita language não pt-BR
- **WHEN** tentativa de persistir voz automática com language ≠ pt-BR
- **THEN** o registry rejeita e não deixa voice_id utilizável no `voice_map`

### Requirement: Escopo obrigatório por book_id
Toda voz gerada automaticamente MUST ser armazenada e resolvida no escopo de um `book_id` estável do audiobook. Personagens com o mesmo `character_id` em livros diferentes MUST NÃO compartilhar automaticamente a mesma pasta/identidade.

#### Scenario: Carlos em dois livros
- **WHEN** dois audiobooks distintos ambos têm `character_id=carlos` sem override
- **THEN** cada um possui (ou gera) identidade sob seu próprio `book_id`

#### Scenario: book_id estável entre reruns
- **WHEN** o mesmo arquivo de input (conteúdo idêntico) é processado de novo, mesmo após rename/move do path
- **THEN** o `book_id` (BLAKE2b-128 do conteúdo) é o mesmo e as vozes existentes são reencontradas
