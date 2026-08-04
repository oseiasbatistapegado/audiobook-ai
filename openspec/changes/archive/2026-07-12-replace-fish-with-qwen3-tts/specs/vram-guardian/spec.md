## MODIFIED Requirements

### Requirement: Três thresholds configuráveis
A configuração central MUST definir e expor:
- `hard_floor_mib` (default 300): mínimo absoluto reservado ao sistema;
- `before_chunk_target_mib` (default 768): headroom desejado antes de um novo chunk com modelo já residente;
- `before_load_target_mib` (por backend, calibrável): headroom exigido antes de carregar/spawnar um modelo.

O load target da fase TTS MUST usar o identificador arquitetural `tts` (e/ou backend concreto `qwen3-tts` quando a calibração for específica do modelo). O default inicial de produto MUST ser **6144 MiB** free antes do load. Defaults Fish `s1-mini` **8192** / `s2-pro` **22528** e a herança implícita “valor do Fish” MUST NÃO permanecer como defaults de produto. Parler MUST manter valor de load **separado**. Um backend desconhecido MUST NÃO herdar implicitamente o load target do TTS. Defaults MUST residir em configuração centralizada. CLI e/ou env MAY sobrescrever com overrides backend-specific. Após o pipeline estável, o target MAY ser recalibrado para `peak observado + margem operacional`; o valor 6144 é margem de integração inicial (~3 GiB observados no smoke), não afirmação de consumo permanente.

#### Scenario: Defaults centralizados TTS
- **WHEN** nenhum override CLI/env é fornecido
- **THEN** o pipeline usa load target **6144 MiB** para `tts` / `qwen3-tts`

#### Scenario: Override via config
- **WHEN** o usuário define reserve/target via flag ou env suportada
- **THEN** as decisões do guardian usam os valores sobrescritos

#### Scenario: Backend desconhecido não herda TTS
- **WHEN** um backend sem default de load explícito é avaliado
- **THEN** o sistema não aplica silenciosamente o `before_load_target_mib` do TTS
