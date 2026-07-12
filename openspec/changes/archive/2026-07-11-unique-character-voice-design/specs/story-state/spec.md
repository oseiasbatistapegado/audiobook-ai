## MODIFIED Requirements

### Requirement: voice_map fixo por personagem
A voz é propriedade do personagem via `voice_map[character_id]` no escopo do audiobook. Após a primeira atribuição bem-sucedida, a voz MUST permanecer fixa. O sistema MUST NÃO escolher voz dinamicamente a cada capítulo. Os voice ids MUST referir-se a identidades com assets de referência **gerados** (ou override do usuário) sob o registry scoped por `book_id`, utilizáveis pelo Fish Speech — MUST NÃO permanecer como IDs simbólicos sem pasta de referência pt-BR, nem como cópias de banco finito apresentadas como geração única.

#### Scenario: Primeira aparição atribui voz gerada
- **WHEN** um personagem aparece pela primeira vez sem entrada em `voice_map`
- **THEN** o sistema gera/persiste uma voz pt-BR sintética e grava em `story.json` do work-dir

#### Scenario: Capítulos seguintes reutilizam voz
- **WHEN** o mesmo `character_id` aparece em um capítulo posterior
- **THEN** o TTS usa a voz já mapeada, sem remapeamento

#### Scenario: voice_id aponta para assets reais gerados
- **WHEN** uma entrada é gravada em `voice_map`
- **THEN** existe (ou é materializada na mesma operação) um diretório resolvível com áudio pt-BR gerado (ou override) para esse personagem no `book_id`
