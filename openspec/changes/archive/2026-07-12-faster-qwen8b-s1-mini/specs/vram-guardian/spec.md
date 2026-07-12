## MODIFIED Requirements

### Requirement: Três thresholds configuráveis
A configuração central MUST definir e expor:
- `hard_floor_mib` (default 300): mínimo absoluto reservado ao sistema;
- `before_chunk_target_mib` (default 768): headroom desejado antes de um novo chunk com modelo já residente;
- `before_load_target_mib` (por backend, calibrável): headroom exigido antes de carregar/spawnar um modelo.

O default de produto (alias Fish `s1-mini`) para load do Fish Speech MUST ser **8192 MiB** free. Quando o alias ativo for `s2-pro` e o usuário NÃO tiver sobrescrito o load target via CLI/env, o sistema MUST aplicar o preset **22528 MiB**. Parler MUST ter valor de load **separado** e calibrado; um backend desconhecido MUST NÃO herdar implicitamente o valor do Fish. Defaults MUST residir em configuração centralizada e MUST NÃO ser duplicados como magic numbers nos backends. CLI e/ou variáveis de ambiente MAY sobrescrever esses valores com overrides backend-specific.

#### Scenario: Defaults centralizados s1-mini
- **WHEN** nenhum override CLI/env é fornecido e o alias Fish é `s1-mini`
- **THEN** o pipeline usa Fish load target 8192 MiB

#### Scenario: Preset s2-pro sem override
- **WHEN** `--fish-model s2-pro` está ativo e o usuário não overrideou o fish load target
- **THEN** o pipeline usa Fish load target 22528 MiB

#### Scenario: Override via config
- **WHEN** o usuário define reserve/target via flag ou env suportada
- **THEN** as decisões do guardian usam os valores sobrescritos (preset do alias não vence o override)

#### Scenario: Backend desconhecido não herda Fish
- **WHEN** um backend sem default de load explícito é avaliado
- **THEN** o sistema não aplica silenciosamente o `before_load_target_mib` do Fish Speech
