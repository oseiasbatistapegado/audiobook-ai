## ADDED Requirements

### Requirement: Abstração VoiceGenerator independente do TTS
O sistema SHALL expor uma abstração `VoiceGenerator` (interface/protocol) com operação `generate_voice(character, language="pt-BR") -> GeneratedVoice`, independente de `TTSBackend` / Fish Speech. A implementação concreta MUST traduzir o perfil semântico do personagem para a representação suportada pelo backend (no MVP: seleção/materialização a partir de banco pt-BR).

#### Scenario: Factory resolve gerador padrão
- **WHEN** o pipeline precisa de uma voz para um personagem novo e o gerador configurado é o MVP (`bank` / equivalente)
- **THEN** o factory retorna um `VoiceGenerator` que produz `GeneratedVoice` com paths de referência utilizáveis pelo Fish Speech

#### Scenario: Gerador não importa Fish Speech
- **WHEN** o módulo do `VoiceGenerator` MVP é carregado
- **THEN** ele MUST NÃO depender de APIs internas do Fish Speech para criar a identidade vocal

### Requirement: Idioma canônico pt-BR na geração
Toda voz gerada ou atribuída automaticamente MUST ter `language` igual a `pt-BR` nos metadados. O sistema MUST NÃO selecionar, gerar ou persistir como default uma voz marcada como `pt-PT`, `en-US` ou idioma genérico sem verificação pt-BR. Ausência de metadados de idioma em asset legado MUST ser tratada como incompatível para atribuição automática.

#### Scenario: GeneratedVoice carrega language
- **WHEN** `generate_voice` conclui com sucesso
- **THEN** o `GeneratedVoice` retornado inclui `language="pt-BR"`

#### Scenario: Banco sem candidatos pt-BR
- **WHEN** o catálogo não contém nenhuma voz base com `language=pt-BR` utilizável para o pedido
- **THEN** a geração falha com erro contextual e NÃO atribui uma voz de outro idioma

### Requirement: Identidade vocal na primeira aparição do personagem
Quando um personagem recebe voz pela primeira vez, o sistema MUST invocar o fluxo de geração/atribuição automática (perfil + gerador + registry) e MUST NÃO exigir que o usuário forneça áudio de referência manual para esse personagem.

#### Scenario: Novo personagem sem voz
- **WHEN** um `character_id` aparece sem entrada em `voice_map` e sem pasta de voz já registrada
- **THEN** o sistema cria/atribui uma voz pt-BR persistente e grava o mapeamento estável

#### Scenario: Mesmo personagem em cena seguinte
- **WHEN** o mesmo `character_id` já possui voz no `voice_map` e no registry
- **THEN** o sistema reutiliza a voz existente sem nova geração

### Requirement: Narrator com voz dedicada pt-BR
O narrador MUST possuir uma voz dedicada pt-BR que MUST NÃO ser selecionada do pool de bases de personagem nem reatribuída a um personagem não-narrador pelo fluxo automático.

#### Scenario: Narrator isolado
- **WHEN** o pipeline atribui vozes a `narrator` e a pelo menos dois personagens
- **THEN** a voz do narrador é distinta das vozes dos personagens e todas têm `language=pt-BR`

### Requirement: Banco de bases extensível sem hardcode de capacidade
O catálogo de vozes base MUST ser descoberto dinamicamente (filesystem/catálogo). A lógica de atribuição MUST NÃO assumir um tamanho fixo hardcoded (ex.: constante `5` ou `6` como capacidade máxima). O MVP SHALL entregar pelo menos 1 narrator + 5 bases de personagem, e bases adicionais MUST entrar no pool automaticamente quando presentes.

#### Scenario: Base adicional entra no pool
- **WHEN** uma nova voz base pt-BR válida é adicionada ao catálogo empacotado
- **THEN** atribuições futuras de personagens podem selecioná-la sem alteração de código de capacidade

### Requirement: Preferir unused e permitir reuse determinístico
Ao atribuir voz a um personagem novo, o gerador MUST preferir bases compatíveis ainda não usadas no audiobook. Quando o pool compatível estiver esgotado, MUST permitir reuse de bases já usadas, escolhido de forma determinística. A atribuição MUST ser materializada imediatamente no registry e permanecer estável. O narrator MUST permanecer excluído do pool de reuse para personagens.

#### Scenario: Preferência por base unused
- **WHEN** existem bases compatíveis ainda não atribuídas a nenhum personagem do livro
- **THEN** o gerador seleciona uma dessas bases unused (de forma determinística entre as candidatas)

#### Scenario: Reuse após esgotamento
- **WHEN** todas as bases compatíveis de personagem já estão em uso e surge um novo personagem
- **THEN** o gerador reutiliza uma base existente de forma determinística, materializa pasta própria no registry para o novo `character_id`, e grava `base_voice_id` na metadata

### Requirement: Seed determinístico estável
Quando o backend suportar seed (ou quando o MVP derivar seleção determinística), o sistema MUST derivar o seed com função de hash estável entre execuções (ex.: BLAKE2b/SHA-256 sobre material canônico). O sistema MUST NÃO usar `hash()` built-in do Python como única fonte de determinismo.

#### Scenario: Mesmo perfil reproduz mesma seleção
- **WHEN** o mesmo `character_id`, perfil canônico e versão de banco são usados em duas execuções limpas sem cache prévio daquele personagem
- **THEN** o `voice_id`/base selecionada (e seed gravado) são idênticos

### Requirement: Falha sem atribuição aleatória silenciosa
Se a geração/atribuição automática falhar, o sistema MUST NÃO gravar em `voice_map` uma voz aleatória não relacionada sem registro. O erro MUST preservar contexto (personagem, motivo) e MUST permitir retry. Fallback MUST, se existir, usar apenas voz pt-BR documentada e MUST registrar aviso explícito.

#### Scenario: Falha não polui voice_map
- **WHEN** `generate_voice` falha para um personagem novo
- **THEN** `voice_map` permanece sem entrada para esse `character_id` (ou marca estado de falha sem voice_id utilizável) e a geração do capítulo aborta ou segue a política de erro documentada sem clone de idioma inválido
