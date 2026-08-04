## ADDED Requirements

### Requirement: Invariante de narração no QA de speakers
O checker de diarização MUST rejeitar qualquer item de `dialogues[]` que não seja fala explícita (turno sem aspas/travessão de diálogo segundo a mesma definição usada para turnos citados) cujo speaker resolvido não seja `narrator` (incluindo equivalentes `narrador`). Isso MUST aplicar-se à prosa em primeira pessoa. A falha MUST ser reportada com prefixo identificável (ex. `speaker QA narration`).

#### Scenario: Prosa de 1ª pessoa no POV é rejeitada
- **WHEN** um diálogo tem texto sem fala explícita e `speaker_id` igual ao protagonista
- **THEN** o checker falha com erro de narração e a resposta NÃO é aceita

#### Scenario: Prosa atribuída a narrator passa
- **WHEN** um diálogo tem texto sem fala explícita e speaker `narrator`
- **THEN** o invariante de narração NÃO rejeita esse item por esse motivo

#### Scenario: Fala explícita do protagonista não é forçada a narrator
- **WHEN** um diálogo é fala explícita (aspas/travessão) com `speaker_id` do protagonista
- **THEN** o invariante de narração NÃO rejeita esse item

### Requirement: Invariante de atribuição explícita no QA de speakers
O checker de diarização MUST detectar padrões de atribuição explícita no texto do próprio turno (ex. `“…” perguntou Horikita`, `Horikita respondeu: “…”`, `disse Sudou` ancorado à fala). Quando o nome/atributo resolve para um personagem conhecido no `story_state` (id, nome ou alias) e esse personagem diverge do speaker do turno, o checker MUST falhar com prefixo identificável (ex. `speaker QA attribution`). Se o nome atribuído NÃO resolve a um personagem conhecido, o checker MUST NÃO falhar somente por esse padrão.

#### Scenario: Fala com “perguntou Horikita” no POV é rejeitada
- **WHEN** o texto do turno contém fala explícita com atribuição resolvível a Horikita e o `speaker_id` é o protagonista
- **THEN** o checker falha com erro de atribuição

#### Scenario: Atribuição alinhada ao speaker passa
- **WHEN** o texto contém `respondeu Horikita` e o speaker do turno resolve para Horikita
- **THEN** o invariante de atribuição NÃO rejeita esse item

#### Scenario: Nome não resolvido não gera falso positivo
- **WHEN** o texto contém `disse AlguémDesconhecido` e esse nome não está no `story_state`
- **THEN** o invariante de atribuição NÃO falha apenas por esse padrão

### Requirement: Dominance permanece como rede de segurança
O detector de colapso global existente (`quoted_turns` mínimo, `dominant_speaker_ratio` ≥ threshold, `evidence_of_multiple_speakers` ≥ 2) MUST permanecer ativo com os defaults de produto atuais. O sistema MUST NÃO tratar a redução do threshold de dominance como substituto dos invariantes locais. A falha de dominance MUST usar prefixo identificável (ex. `speaker QA dominance`).

#### Scenario: ch-004 falha por invariante local com dominance baixa
- **WHEN** a fixture de regressão `ch-004` (prosa no POV e/ou fala de Horikita no protagonista) é avaliada e o `dominant_speaker_ratio` é inferior ao threshold de dominance
- **THEN** o checker ainda falha por narração e/ou atribuição

#### Scenario: ch-011 continua rejeitado por dominance
- **WHEN** a fixture `ch-011` de colapso global é avaliada
- **THEN** o checker falha (por dominance e/ou outros invariantes aplicáveis)

### Requirement: QA de diarização separado de qualidade PT-BR
O checker de speakers MUST NÃO rejeitar respostas com base em qualidade de adaptação, calques, mistura de inglês, ou fluência do português brasileiro. Critérios de idioma/adaptação MUST permanecer fora deste gate (change futura separada, se houver).

#### Scenario: Texto calque com speakers corretos passa no gate de speakers
- **WHEN** os diálogos têm speakers corretos segundo os invariantes mas o texto contém calque ou inglês residual
- **THEN** o checker de diarização NÃO falha por esse motivo

### Requirement: Política de cache bump para invariantes locais
Alterar os invariantes locais de QA MUST incrementar `LLM_DIARIZATION_POLICY_VERSION` (ou equivalente na chave de cache) de modo que caches aceitos apenas sob o gate de dominance antigo NÃO façam hit.

#### Scenario: Cache miss após introdução dos invariantes locais
- **WHEN** existe cache válido gerado sob a política de diarização anterior à introdução dos invariantes de narração/atribuição
- **THEN** `interpret_chapter` NÃO reutiliza essa entrada
