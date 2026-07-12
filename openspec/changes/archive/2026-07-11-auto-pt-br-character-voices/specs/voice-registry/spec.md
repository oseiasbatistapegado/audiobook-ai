## ADDED Requirements

### Requirement: Persistência de vozes no cache
O sistema SHALL persistir cada voz gerada/atribuída sob um diretório de cache de vozes (default sob o cache root do app, ex.: `~/.cache/audiobook-ai/voices/<voice_id>/`) contendo no mínimo `metadata.json` e `reference.wav`, mais texto de referência alinhado (`reference.lab` ou `reference.txt`). O registry MUST sobreviver a reinício do processo/aplicação.

#### Scenario: Cache sobrevive restart
- **WHEN** uma voz é materializada no registry e a aplicação reinicia
- **THEN** uma nova resolução do mesmo `voice_id` reutiliza os arquivos em disco sem regenerar

#### Scenario: Metadata inclui language e proveniência
- **WHEN** uma voz é persistida pelo fluxo automático
- **THEN** `metadata.json` inclui `language` igual a `pt-BR`, `base_voice_id` da base de origem, e proveniência de geração (gerador e seed quando aplicável)

### Requirement: Persistido vence reatribuição futura
Se o registry já contém uma voz válida pt-BR para um `character_id`, o sistema MUST reutilizá-la e MUST NÃO substituí-la por uma nova seleção do banco só porque o algoritmo de atribuição ou a versão do catálogo mudou.

#### Scenario: Pasta existente bloqueia re-seleção
- **WHEN** `voices/<character_id>/` já existe com wav + metadata pt-BR válidos
- **THEN** o ensure/get retorna essa voz sem sobrescrever `reference.wav` nem alterar `base_voice_id` gravado

### Requirement: Lookup e materialização idempotente
`VoiceRegistry` (ou equivalente) MUST oferecer operação de ensure/get que, se a pasta da voz já existir e for válida (wav + language pt-BR), retorna essa voz sem sobrescrever; se não existir, materializa a partir do `GeneratedVoice` / banco base.

#### Scenario: Ensure não sobrescreve voz válida
- **WHEN** `ensure` é chamado para um `voice_id` que já tem `reference.wav` e metadata pt-BR válidos
- **THEN** os arquivos existentes permanecem inalterados e o voice_id é reutilizado

#### Scenario: Ensure materializa ausente
- **WHEN** `ensure` é chamado para um `voice_id` ausente e o gerador produziu paths/conteúdo válidos
- **THEN** o registry cria a pasta e arquivos necessários no cache

### Requirement: Precedência de resolução de referência
A resolução de diretório de voz para o TTS MUST respeitar a ordem: (1) override do usuário `./references/<voice_id>/`, (2) registry/cache de vozes, (3) assets empacotados `assets/voices/<voice_id>/`. Uma referência só é elegível para uso automático se estiver marcada ou validada como `pt-BR` conforme regras do gerador/registry.

#### Scenario: Override do usuário vence cache
- **WHEN** existem tanto `./references/carlos/` quanto cache `voices/carlos/`
- **THEN** o backend de resolução usa o override do usuário para síntese

#### Scenario: Cache vence asset empacotado para o mesmo id
- **WHEN** o registry possui `voices/carlos/` válido e também existe asset empacotado com o mesmo id
- **THEN** a síntese usa a voz do registry/cache

### Requirement: Proibição de voz de idioma inválido no registry automático
O registry MUST NÃO aceitar como sucesso de materialização automática uma voz cujo metadata declare idioma diferente de `pt-BR` (ou omita idioma, para assets novos do fluxo automático).

#### Scenario: Rejeita language não pt-BR
- **WHEN** uma tentativa de persistir voz com `language=pt-PT` (ou outro não pt-BR) ocorre no fluxo automático
- **THEN** o registry rejeita a operação com erro e não deixa o voice_id utilizável no `voice_map`
