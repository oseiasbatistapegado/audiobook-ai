## ADDED Requirements

### Requirement: Passagem de descoberta de elenco antes da diarização
O sistema SHALL executar uma passagem LLM de descoberta de elenco (Pass 1) para cada capítulo **antes** de qualquer unidade de interpretação/diarização (Pass 2) daquele capítulo. Pass 1 MUST analisar o texto-fonte do capítulo junto com o `story_state` acumulado e MUST produzir um chapter cast resolvido (personagens presentes/relevantes, aliases, participação chapter-local speaker/mentioned) validado por schema Pydantic. Pass 1 MUST NÃO emitir a lista final de `dialogues[]` traduzidos nem atribuição completa de speakers por turno (sem diarização turn-level).

#### Scenario: Discovery precede interpret
- **WHEN** o backend inicia a interpretação de um capítulo
- **THEN** a chamada de cast discovery completa (ou resolve via cache) antes da primeira unidade Pass 2

#### Scenario: Pass 1 não devolve diálogos finais
- **WHEN** Pass 1 retorna JSON válido
- **THEN** o contrato de saída NÃO é o `LLMChapterResponse` de diálogos finais (é o schema de discovery)

### Requirement: Cobertura completa do texto-fonte na Pass 1
Pass 1 MUST receber o texto-fonte bruto **completo** do capítulo sempre que esse texto couber no contexto suportado/configurado do modelo. O sistema MUST NÃO usar sampling silencioso `head+tail` (nem qualquer amostragem parcial) para discovery. Quando uma única chamada for impossível por limite de contexto, o sistema MUST aplicar chunking determinístico de **cobertura total** do capítulo, descobrir cast por chunk e mesclar os resultados com a mesma lógica de identidade/aliases do story, produzindo um único chapter cast antes da Pass 2.

#### Scenario: Capítulo cabe no contexto
- **WHEN** o texto completo do capítulo cabe no contexto de Pass 1
- **THEN** o sistema faz discovery em uma única chamada com o capítulo inteiro

#### Scenario: Capítulo excede contexto usa chunking completo
- **WHEN** o texto do capítulo excede o contexto suportado de Pass 1
- **THEN** o sistema particiona o capítulo de forma determinística cobrindo 100% do texto, mescla os casts parciais e NÃO amostra apenas início/fim

#### Scenario: Head-tail sampling proibido
- **WHEN** Pass 1 é planejada para um capítulo longo
- **THEN** a implementação NÃO escolhe head+tail como estratégia de discovery

### Requirement: Participação chapter-local speaker vs mentioned
Pass 1 MUST classificar a participação de cada personagem no capítulo de forma chapter-local (no mínimo: pode falar vs apenas mencionado; um booleano `speaks` ou enum `speaker`/`mentioned` é aceitável no MVP; `possible_speaker` MAY ser incluído e conta como elegível ao speaker set). Essa classificação MUST NÃO ser gravada como propriedade persistente de identidade no modelo global `Character` (um personagem pode ser speaker no capítulo A e mentioned-only no B). Pass 1 MUST NÃO realizar diarização por turno.

#### Scenario: Mentioned-only não redefine Character global
- **WHEN** Pass 1 marca `manabu_horikita` como mentioned no capítulo atual
- **THEN** o `Character` persistido NÃO ganha um campo global fixo `role=mentioned`

#### Scenario: Speaker e mentioned coexistem no chapter cast
- **WHEN** o capítulo tem Horikita falando e o irmão apenas referido
- **THEN** o chapter cast inclui ambos, com participação distinta (speaker vs mentioned)

### Requirement: Saída enxuta e reuso de identidades do story
Pass 1 MUST preferir `character_id` já presentes no `story_state` quando aliases/nomes referem o mesmo personagem. Personagens novos MUST receber ids estáveis e MAY incluir `voice_profile` opcional. Pass 1 MUST NÃO criar identidades duplicadas para aliases conhecidos (ex. Suzune / Horikita / Horikita-san).

#### Scenario: Alias resolve para personagem existente
- **WHEN** o capítulo refere “Horikita-san” e `Horikita` já está no `story_state`
- **THEN** o chapter cast reutiliza `Horikita` (possivelmente registrando alias), sem novo id paralelo

#### Scenario: Personagem novo entra no chapter cast
- **WHEN** um falante aparece pela primeira vez no capítulo e não resolve a nenhum id do story
- **THEN** Pass 1 inclui um novo personagem com id estável no chapter cast

### Requirement: Cache de cast discovery
O sistema MUST cachear respostas válidas de Pass 1 com chave distinta da interpretação Pass 2, incluindo identidade do capítulo, hash do texto do capítulo, modelo, fingerprint do story cast e versões de política aplicáveis. Hit de cache MUST pular a chamada Ollama de discovery.

#### Scenario: Cache hit de discovery
- **WHEN** Pass 1 já foi cacheada com a mesma chave
- **THEN** o backend reutiliza o chapter cast sem nova chamada Ollama de discovery

#### Scenario: Mudança de política invalida cache de discovery
- **WHEN** a versão de política de diarização/cast muda
- **THEN** caches Pass 1 anteriores NÃO são reutilizados como sucesso

### Requirement: Prompt externo de discovery
O prompt de Pass 1 MUST residir em arquivo sob `llm/prompts/` (separado do prompt de interpretação) e MUST NÃO ser string hardcoded no código de chamada. O prompt MUST pedir quem existe no capítulo, quem pode falar vs mentioned, e aliases — MUST NÃO pedir atribuição de speakers por turno.

#### Scenario: Carregamento do prompt de discovery
- **WHEN** o backend executa Pass 1
- **THEN** o texto do prompt é lido do arquivo de prompts de discovery correspondente
