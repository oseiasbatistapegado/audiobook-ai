## ADDED Requirements

### Requirement: Chapter cast merge sem duplicar identidades
Após Pass 1, o sistema MUST mesclar personagens novos do chapter cast no `StoryState` persistível reutilizando ids existentes quando aliases/nomes resolvem ao mesmo personagem. A merge MUST NÃO criar entradas duplicadas em `characters` para o mesmo indivíduo narrativo. Voice generation / `voice_map` MUST continuar lazy: existência do personagem no story precede atribuição de fala; geração de voz MUST NÃO ser exigida antes da Pass 2 e MUST NÃO ser disparada em duplicata por causa da Pass 1. Participação speaker/mentioned MUST permanecer metadata chapter-local e MUST NÃO ser persistida como propriedade fixa de identidade em `Character`.

#### Scenario: Novo falante entra no story sem voz ainda
- **WHEN** Pass 1 descobre `blond_boy` ausente do story
- **THEN** o personagem pode ser mesclado no estado de trabalho antes da Pass 2 mesmo sem entrada em `voice_map`

#### Scenario: Pass 1 não regenera voz existente
- **WHEN** `Horikita` já tem `voice_map` e Pass 1 a reutiliza no chapter cast
- **THEN** o sistema NÃO regenera a voz de `Horikita` por causa da discovery

#### Scenario: Alias novo não duplica personagem
- **WHEN** Pass 1 registra alias “Horikita-san” para id `Horikita` já existente
- **THEN** `story.characters` permanece com um único `Horikita` e o alias fica associado a esse id

#### Scenario: Participação não vira campo global de Character
- **WHEN** Pass 1 classifica um personagem como mentioned-only no capítulo
- **THEN** o merge no `story.json` NÃO grava um `role`/`participation` persistente nesse `Character`
