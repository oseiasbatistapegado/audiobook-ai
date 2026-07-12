## Purpose

Persistir estado narrativo em `story.json` (default `out/story.json`) com IDs estáveis de personagens e `voice_map` fixo.

## Requirements

### Requirement: Fonte única de verdade em story.json sob out/
O sistema SHALL persistir o estado da história em um único arquivo `story.json` cujo caminho default MUST ser `out/story.json` (work-dir default `out/` na raiz do projeto). Nenhum outro módulo MUST manter estado paralelo de personagens ou vozes. O schema MUST ser Pydantic (`StoryState`). Override de work-dir via CLI MUST relocar `story.json` para `<work-dir>/story.json`.

#### Scenario: Carregar estado existente
- **WHEN** `out/story.json` (ou `<work-dir>/story.json`) já existe
- **THEN** o pipeline carrega `StoryState` tipado e o reutiliza nos capítulos seguintes

#### Scenario: Criar estado inicial
- **WHEN** `story.json` não existe no início da geração
- **THEN** o sistema cria um `StoryState` vazio (ou mínimo) e o persiste sob o work-dir (`out/` por default) após atualizações

### Requirement: Personagens com ID permanente
Cada personagem MUST possuir um ID estável. Nomes, apelidos e títulos MUST mapear para o mesmo ID quando identificados como o mesmo personagem. O estado MUST NÃO identificar personagens apenas pelo nome exibido.

#### Scenario: Alias aponta para o mesmo personagem
- **WHEN** `story_updates` registra um alias para um `character_id` existente
- **THEN** diálogos posteriores que usam o alias resolvem para o mesmo ID e a mesma voz

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
