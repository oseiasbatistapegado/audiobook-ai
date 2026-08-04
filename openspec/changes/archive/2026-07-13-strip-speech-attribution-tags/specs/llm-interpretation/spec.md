## ADDED Requirements

### Requirement: Strip de speech-tags de atribuição em falas de personagem
Após validação Pydantic e antes do gate de QA de diarização, o sistema MUST aplicar um repair determinístico que remove speech-tags de atribuição do `dialogues[].text` de turnos cujo speaker NÃO seja `narrator`. Tags cobertas MUST incluir padrões ancorados à fala do tipo `“, disse ela.”`, `” perguntou ela.”`, `” respondeu Horikita.”` e equivalentes com verbos de fala comuns (PT/EN) seguidos de `ela`/`ele`/nome. O repair MUST descartar a tag (não criar turno `narrator` separado). Turnos `narrator` MUST NÃO ser alterados por este repair. Se após o strip o texto ficar vazio, o sistema MUST tratar isso como falha de interpretação (retry/erro), não como sucesso.

#### Scenario: “perguntou ela” é removido da fala
- **WHEN** um diálogo de personagem tem texto `"Prova?, perguntou ela."`
- **THEN** após o repair o texto fica equivalente a `"Prova?"` (sem a tag `perguntou ela`) e o speaker permanece o do personagem

#### Scenario: “disse ela” é removido da fala
- **WHEN** um diálogo de personagem tem texto `"Como eu sabia, você já estava acordado, disse ela."`
- **THEN** após o repair a tag `, disse ela` é removida e só a fala permanece

#### Scenario: Narrador com “disse que” não é stripado
- **WHEN** um turno `narrator` contém prosa como `um grande pensador disse que o céu…`
- **THEN** o repair de speech-tag NÃO altera esse texto

### Requirement: Invariante de speech-tag residual no QA de speakers
O checker de diarização MUST rejeitar turnos de personagem (speaker não-`narrator`) cujo `text` ainda contenha speech-tag de atribuição residual (mesmo padrão do strip, incluindo pronomes `ela`/`ele`). A falha MUST usar prefixo identificável (ex. `speaker QA speech-tag`) e MUST consumir tentativa de retry como as demais falhas de QA. Turnos `narrator` MUST NÃO falhar somente por conter verbos de fala em prosa.

#### Scenario: Tag residual em personagem falha o QA
- **WHEN** após o repair (ou na ausência dele) um turno de personagem ainda contém `perguntou ela` / `disse ela` colado à fala
- **THEN** o checker falha com erro de speech-tag e a resposta NÃO é aceita como interpretação final

#### Scenario: Fala limpa passa
- **WHEN** o turno de personagem contém apenas a fala entre aspas sem tag de atribuição
- **THEN** o invariante de speech-tag NÃO rejeita esse item

#### Scenario: Fixture ch-004 speech-tag
- **WHEN** a fixture de regressão derivada de `ch-004` com `"…, disse ela."` / `"Prova?, perguntou ela."` é avaliada sem strip (ou com strip desabilitado no teste do checker)
- **THEN** o checker falha por speech-tag

### Requirement: Prompt proíbe speech-tags no texto falado
O arquivo de prompt de interpretação MUST instruir que `dialogues[].text` de personagem MUST conter apenas as palavras faladas e MUST NOT incluir tags narrativas de atribuição (`disse`/`perguntou`/`respondeu`/… + `ela`/`ele`/Nome). A atribuição no texto-fonte MUST informar apenas o `speaker_id`/`speaker_name` do turno.

#### Scenario: Prompt inclui regra de texto falado limpo
- **WHEN** o backend carrega o prompt de interpretação
- **THEN** o texto do prompt inclui a proibição de speech-tags de atribuição dentro do `text` de falas de personagem

## MODIFIED Requirements

### Requirement: Prompt exige atribuição correta de speakers
O arquivo de prompt de interpretação sob `llm/prompts/` MUST instruir regras explícitas de diarização compatíveis com `qwen3:8b`: prosa narrativa (incluindo 1ª pessoa) MUST usar speaker `narrator`; fala explícita do POV/protagonista MUST usar o `character_id` do protagonista (não `narrator`); cada turno de fala MUST ter exatamente um speaker; MUST NÃO misturar falas de personagens distintos no mesmo `dialogues[].text`; MUST preferir ids do `story_state` e registrar personagens novos em `story_updates.characters`; pistas de atribuição no texto-fonte MUST coincidir com o speaker do turno e MUST NÃO ser copiadas para dentro do `dialogues[].text` falado (a voz do turn identifica o falante). O prompt MAY esclarecer que `speaker_id` identifica papel narrativo e NÃO implica por si só uma `voice_id` distinta.

#### Scenario: Prompt carrega regras de diarização
- **WHEN** o backend carrega o prompt de interpretação para uma chamada Ollama
- **THEN** o texto do prompt inclui prosa/1ª pessoa → `narrator`, fala do POV → protagonist id, um speaker por turno de fala, proibição de misturar falantes no mesmo `text`, proibição de speech-tags de atribuição no texto falado, e reuso/registro de personagens

#### Scenario: Narração em 1ª pessoa não usa o protagonist id
- **WHEN** o texto é prosa em 1ª pessoa sem fala explícita entre aspas/travessão
- **THEN** a resposta válida atribui esse segmento a `narrator`, não ao `character_id` do protagonista

### Requirement: Gate de QA semântica de diarização pós-schema
Após JSON parseável e validação Pydantic de `LLMChapterResponse`, o sistema MUST aplicar repairs determinísticos aplicáveis (incluindo coerção de prosa→`narrator` e strip de speech-tags em falas de personagem) e em seguida um checker determinístico de qualidade de diarização. Se a resposta falhar o checker, MUST ser tratada como falha de interpretação (não cacheada como sucesso) e MUST entrar no fluxo de retry com mensagem de erro acionável descrevendo a falha de QA. O checker MUST NÃO exigir um segundo modelo LLM. Defaults de produto MUST ser: `LLM_SPEAKER_QA_MIN_QUOTED_TURNS=6`, `LLM_SPEAKER_QA_DOMINANCE_THRESHOLD=0.85`. O detector de colapso global MUST falhar quando, simultaneamente: `quoted_turns >= LLM_SPEAKER_QA_MIN_QUOTED_TURNS` AND `dominant_speaker_ratio >= LLM_SPEAKER_QA_DOMINANCE_THRESHOLD` AND `evidence_of_multiple_speakers >= 2`. `evidence_of_multiple_speakers` MUST considerar personagens conhecidos no `story_state` e atribuições explícitas locais (ex. “disse Sudou”, “respondeu Horikita”), além do speaker dominante. O caso de regressão `ch-011` MUST ser coberto por fixture de teste obrigatória. O caso de regressão de speech-tag `ch-004` (`disse ela` / `perguntou ela`) MUST ser coberto por fixture de teste obrigatória.

#### Scenario: Colapso de speakers em turnos falados rejeitado
- **WHEN** uma resposta schema-válida tem `quoted_turns >= 6`, `dominant_speaker_ratio >= 0.85` para um speaker não-`narrator`, e `evidence_of_multiple_speakers >= 2` no texto da unidade
- **THEN** o checker falha, a resposta NÃO é aceita como interpretação final, e o backend solicita nova tentativa incluindo o erro de QA

#### Scenario: Monólogo sem múltiplos falantes passa no QA
- **WHEN** uma resposta schema-válida tem `quoted_turns < 6` ou `evidence_of_multiple_speakers < 2`
- **THEN** o checker NÃO rejeita a resposta apenas por baixa diversidade de `speaker_id`

#### Scenario: QA failure não grava cache de sucesso
- **WHEN** a resposta falha no checker de diarização
- **THEN** o backend NÃO grava essa resposta no cache de interpretação como sucesso

#### Scenario: Fixture ch-011 rejeita colapso conhecido
- **WHEN** o checker recebe a fixture de regressão derivada do `ch-011` com falas de Sudou/Ike/Yamauchi atribuídas ao protagonista
- **THEN** o checker falha

#### Scenario: Fixture ch-004 speech-tag é coberta pelo pipeline de QA
- **WHEN** a fixture de speech-tag derivada de `ch-004` é processada pelo fluxo repair+checker
- **THEN** ou o strip remove as tags e a resposta passa no invariante de speech-tag, ou tags residuais fazem o checker falhar com prefixo de speech-tag

### Requirement: Política de cache inclui diarização/QA
A chave de cache de interpretação MUST incorporar um identificador estável da política de diarização/QA (além de locale/adaptação PT-BR, modelo, capítulo/unidade e payload). Alterar essa política MUST impedir hit em caches gerados sob política anterior. A introdução do strip/invariante de speech-tag MUST bump a versão de política de diarização (ex. `v5` → `v6`).

#### Scenario: Cache miss após bump de política de diarização
- **WHEN** existe cache válido gerado sob política de diarização anterior para o mesmo modelo e texto
- **THEN** `interpret_chapter` NÃO reutiliza essa entrada

#### Scenario: Cache miss após política v6 de speech-tag
- **WHEN** existe cache gerado sob `v5` (ou anterior) sem strip de speech-tag
- **THEN** a interpretação sob a nova política NÃO reutiliza essa entrada
