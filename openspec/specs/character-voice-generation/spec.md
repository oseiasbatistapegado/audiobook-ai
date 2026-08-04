## Purpose

Geração/atribuição automática de vozes pt-BR por personagem via abstração `VoiceGenerator`, independente do backend TTS.

## Requirements

### Requirement: Abstração VoiceGenerator independente do TTS
O sistema SHALL expor uma abstração `VoiceGenerator` (interface/protocol) com operação `generate_voice(character, language="pt-BR") -> GeneratedVoice`, independente de `TTSBackend` / Qwen3-TTS. A implementação concreta MVP MUST ser um backend de **voice design generativo** (candidato: Parler-TTS pt-BR) que cria identidade sintética nova e materializa referência pt-BR — MUST NÃO ser seleção/cópia de um catálogo finito de bases.

#### Scenario: Factory resolve gerador padrão
- **WHEN** o pipeline precisa de uma voz para um personagem novo e o gerador configurado é o MVP generativo
- **THEN** o factory retorna um `VoiceGenerator` que produz `GeneratedVoice` com referência sintética nova utilizável pelo Qwen3-TTS Voice Clone

#### Scenario: Gerador não importa backend TTS
- **WHEN** o módulo do `VoiceGenerator` MVP é carregado
- **THEN** ele MUST NÃO depender de APIs internas do backend TTS para criar a identidade vocal

### Requirement: Idioma canônico pt-BR na geração
Toda voz gerada automaticamente MUST ter `language` igual a `pt-BR` nos metadados e na fala de referência. O sistema MUST NÃO persistir como sucesso uma referência com sotaque europeu inaceitável, inglês, ou idioma genérico sem verificação auditiva/pt-BR. Portuguese genérico na documentação do modelo MUST NÃO ser tratado como prova de pt-BR.

#### Scenario: GeneratedVoice carrega language
- **WHEN** `generate_voice` conclui com sucesso
- **THEN** o `GeneratedVoice` retornado inclui `language="pt-BR"`

#### Scenario: Falha de qualidade pt-BR
- **WHEN** a geração produz áudio que não passa o critério de aceite pt-BR do smoke
- **THEN** a operação é tratada como falha (sem gravar identidade “válida” no voice_map)

### Requirement: Identidade vocal na primeira aparição do personagem
Quando um personagem recebe voz pela primeira vez no audiobook, o sistema MUST invocar Voice Design generativo (perfil + seed + registry scoped) e MUST NÃO exigir áudio de referência manual. MUST NÃO satisfazer o requisito apenas copiando/renomeando uma base de catálogo.

#### Scenario: Novo personagem sem voz
- **WHEN** um `character_id` aparece sem entrada em `voice_map` e sem pasta de voz no registry do `book_id`
- **THEN** o sistema gera uma voz sintética pt-BR persistente e grava o mapeamento estável

#### Scenario: Mesmo personagem em cena seguinte
- **WHEN** o mesmo `character_id` já possui voz no `voice_map` e no registry do livro
- **THEN** o sistema reutiliza a voz persistida sem nova geração

### Requirement: Narrator com voz dedicada pt-BR
O narrador MUST possuir uma identidade vocal dedicada pt-BR (gerada ou explicitamente configurada) que MUST NÃO ser compartilhada com nenhum personagem.

#### Scenario: Narrator isolado
- **WHEN** o pipeline atribui vozes a `narrator` e a pelo menos dois personagens
- **THEN** as três identidades são perceptualmente distintas e todas em pt-BR

### Requirement: Seed determinístico estável
O sistema MUST derivar o seed com hash criptográfico estável (BLAKE2b ou SHA-256) sobre `book_id`, `character_id`, perfil vocal canônico e identificador/versão do gerador/modelo. MUST NÃO usar `hash()` do Python. A referência persistida permanece a identidade canônica após sucesso.

#### Scenario: Mesmo personagem no mesmo livro
- **WHEN** o mesmo `book_id`, `character_id`, perfil e versão de gerador são usados sem cache prévio
- **THEN** o seed derivado é idêntico; se a ref já existe, é reutilizada sem regenerar

### Requirement: Falha sem atribuição aleatória silenciosa
Se a geração única falhar, o sistema MUST NÃO gravar stock voice, voz de outro personagem, referência inglês, nem `voice_id` simbólico sem ref utilizável. O erro MUST preservar contexto e permitir retry.

#### Scenario: Falha não polui voice_map
- **WHEN** `generate_voice` falha para um personagem novo
- **THEN** `voice_map` permanece sem entrada utilizável para esse `character_id` e o personagem fica unresolved até retry bem-sucedido
