## MODIFIED Requirements

### Requirement: voice_map fixo por personagem
A voz é propriedade do personagem via `voice_map[character_id]`. Após a primeira atribuição, a voz MUST permanecer fixa pelo restante do livro. O sistema MUST NÃO escolher voz dinamicamente a cada capítulo para o mesmo ID. Os voice ids MUST referir-se a identidades vocais **locais** com assets de referência utilizáveis pelo Fish Speech (registry/cache e/ou `assets/voices/`), não a IDs de API cloud e MUST NÃO permanecer como identificadores simbólicos sem pasta de referência pt-BR correspondente. A primeira atribuição MUST passar pelo fluxo de geração/registro automático de voz pt-BR.

#### Scenario: Primeira aparição atribui voz
- **WHEN** um personagem aparece pela primeira vez sem entrada em `voice_map`
- **THEN** o sistema atribui uma voz pt-BR disponível (gerada/registrada) com assets reais e grava em `out/story.json` (ou work-dir configurado)

#### Scenario: Capítulos seguintes reutilizam voz
- **WHEN** o mesmo `character_id` aparece em um capítulo posterior
- **THEN** o TTS usa a voz já mapeada, sem remapeamento

#### Scenario: voice_id aponta para assets reais
- **WHEN** uma entrada é gravada em `voice_map`
- **THEN** existe (ou é materializada na mesma operação) um diretório de referência resolvível para esse `voice_id` com áudio pt-BR utilizável
