## Purpose

Particionar capítulos longos em unidades de interpretação LLM ordenadas, interpretar com story state acumulado e agregar o resultado no capítulo lógico.

## Requirements

### Requirement: Particionar capítulos longos em unidades de interpretação
Quando o texto de um capítulo exceder o limiar configurável `LLM_INTERPRET_MAX_CHARS` (default de produto **6000**), o sistema MUST dividir o capítulo em uma ou mais unidades de interpretação ordenadas, cada uma com tamanho ≤ limiar (salvo um único parágrafo/sentença indivisível maior que o limiar, que MUST formar a menor unidade possível). A divisão MUST preferir fronteiras de parágrafo e, se necessário, de sentença. Capítulos sob o limiar MUST ser interpretados como uma única unidade.

#### Scenario: Default de produto é 6000 caracteres
- **WHEN** nenhuma override de config/CLI/env redefine o limiar
- **THEN** o sistema usa `LLM_INTERPRET_MAX_CHARS=6000`

#### Scenario: Capítulo curto permanece uma unidade
- **WHEN** `len(chapter.text)` é menor ou igual a `LLM_INTERPRET_MAX_CHARS`
- **THEN** o sistema interpreta o capítulo como exatamente uma unidade

#### Scenario: Capítulo longo vira múltiplas unidades
- **WHEN** `len(chapter.text)` excede `LLM_INTERPRET_MAX_CHARS` e há fronteiras de parágrafo disponíveis
- **THEN** o sistema produz duas ou mais unidades ordenadas cobrindo o texto completo sem sobreposição, cada uma preferencialmente ≤ limiar

### Requirement: Interpretar unidades em ordem com story state acumulado
O sistema MUST interpretar as unidades de um capítulo em ordem sequencial. Cada unidade MUST receber o `story_state` já atualizado pelas unidades anteriores do mesmo capítulo. Falha permanente em uma unidade (após retries) MUST abortar a interpretação do capítulo com erro contextual que identifique a unidade.

#### Scenario: Personagem novo na unidade 1 visível na unidade 2
- **WHEN** a unidade 1 registra um personagem novo em `story_updates` e a unidade 2 é interpretada em seguida
- **THEN** o payload da unidade 2 inclui esse personagem no `story_state`

#### Scenario: Falha na unidade do meio aborta o capítulo
- **WHEN** a unidade 2 de 3 esgota as tentativas de interpretação
- **THEN** o sistema NÃO aceita o capítulo como interpretado e reporta erro referenciando o capítulo e a unidade 2

### Requirement: Agregar resultados das unidades no capítulo lógico
Após sucesso de todas as unidades de um capítulo, o sistema MUST concatenar `dialogues` na ordem das unidades e MUST agregar `story_updates` de forma determinística (personagens por id; aliases como união; conflitos de `voice_profile` resolvidos pela última unidade que definiu o id). O manifesto/chunks do capítulo MUST refletir a sequência agregada como se fosse uma única interpretação lógica do capítulo.

#### Scenario: Diálogos preservam ordem do texto
- **WHEN** um capítulo é dividido em duas unidades com diálogos D1 e D2 respectivamente
- **THEN** a resposta agregada lista os diálogos de D1 antes dos de D2

#### Scenario: Aliases de unidades distintas são unidos
- **WHEN** a unidade 1 adiciona alias A e a unidade 2 adiciona alias B para o mesmo `character_id`
- **THEN** o `story_updates` agregado inclui A e B para esse id

### Requirement: Cache de interpretação por unidade
O cache de interpretação MUST endereçar cada unidade (não apenas o capítulo inteiro quando houver split), de modo que unidades bem-sucedidas possam ser reutilizadas em reexecuções sem reprocessar o capítulo completo. A chave MUST incluir o identificador de política de interpretação vigente.

#### Scenario: Reexecução reutiliza unidade já cacheada
- **WHEN** a unidade 1 de um capítulo longo está em cache válido sob a política atual e a unidade 2 ainda não
- **THEN** o sistema MAY reutilizar o cache da unidade 1 e chama o LLM apenas para a unidade 2 (ou unidades faltantes)
