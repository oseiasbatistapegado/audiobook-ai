## ADDED Requirements

### Requirement: Prompt exige atribuição correta de speakers
O arquivo de prompt de interpretação sob `llm/prompts/` MUST instruir regras explícitas de diarização compatíveis com `qwen3:8b`: prosa narrativa (incluindo 1ª pessoa) MUST usar speaker `narrator`; fala explícita do POV/protagonista MUST usar o `character_id` do protagonista (não `narrator`); cada turno de fala MUST ter exatamente um speaker; MUST NÃO misturar falas de personagens distintos no mesmo `dialogues[].text`; MUST preferir ids do `story_state` e registrar personagens novos em `story_updates.characters`; pistas de atribuição no texto MUST coincidir com o speaker do turno. O prompt MAY esclarecer que `speaker_id` identifica papel narrativo e NÃO implica por si só uma `voice_id` distinta.

#### Scenario: Prompt carrega regras de diarização
- **WHEN** o backend carrega o prompt de interpretação para uma chamada Ollama
- **THEN** o texto do prompt inclui prosa/1ª pessoa → `narrator`, fala do POV → protagonist id, um speaker por turno de fala, proibição de misturar falantes no mesmo `text`, e reuso/registro de personagens

#### Scenario: Narração em 1ª pessoa não usa o protagonist id
- **WHEN** o texto é prosa em 1ª pessoa sem fala explícita entre aspas/travessão
- **THEN** a resposta válida atribui esse segmento a `narrator`, não ao `character_id` do protagonista

### Requirement: Gate de QA semântica de diarização pós-schema
Após JSON parseável e validação Pydantic de `LLMChapterResponse`, o sistema MUST aplicar um checker determinístico de qualidade de diarização. Se a resposta falhar o checker, MUST ser tratada como falha de interpretação (não cacheada como sucesso) e MUST entrar no fluxo de retry com mensagem de erro acionável descrevendo a falha de QA. O checker MUST NÃO exigir um segundo modelo LLM. Defaults de produto MUST ser: `LLM_SPEAKER_QA_MIN_QUOTED_TURNS=6`, `LLM_SPEAKER_QA_DOMINANCE_THRESHOLD=0.85`. O checker MUST falhar somente quando, simultaneamente: `quoted_turns >= LLM_SPEAKER_QA_MIN_QUOTED_TURNS` AND `dominant_speaker_ratio >= LLM_SPEAKER_QA_DOMINANCE_THRESHOLD` AND `evidence_of_multiple_speakers >= 2`. `evidence_of_multiple_speakers` MUST considerar personagens conhecidos no `story_state` e atribuições explícitas locais (ex. “disse Sudou”, “respondeu Horikita”), além do speaker dominante. O caso de regressão `ch-011` (falas de terceiros colapsadas no protagonista) MUST ser coberto por fixture de teste obrigatória.

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

### Requirement: Retries cobrem JSON, schema e QA
O backend de interpretação MUST permitir até `LLM_INTERPRET_MAX_ATTEMPTS` tentativas por unidade de interpretação, com default de produto `3`. Falhas de parse JSON, validação Pydantic e QA de diarização MUST consumir tentativas e MUST incluir o erro específico na mensagem de retry. Após esgotar as tentativas, o sistema MUST abortar com erro contextual (capítulo/unidade, backend, motivo). O sistema MAY aplicar reparo mecânico mínimo de JSON (ex.: trailing commas) antes de declarar falha de parse, sem inventar conteúdo narrativo.

#### Scenario: Terceira tentativa recupera após QA
- **WHEN** as duas primeiras respostas falham no QA de diarização e a terceira passa schema + QA
- **THEN** o backend aceita a terceira resposta e pode cacheá-la como sucesso

#### Scenario: Esgotamento de tentativas aborta com contexto
- **WHEN** todas as tentativas configuradas falham por JSON, schema ou QA
- **THEN** o sistema aborta a interpretação com erro que identifica o capítulo (e unidade, se aplicável), o backend e o último motivo de falha

### Requirement: Política de cache inclui diarização/QA
A chave de cache de interpretação MUST incorporar um identificador estável da política de diarização/QA (além de locale/adaptação PT-BR, modelo, capítulo/unidade e payload). Alterar essa política MUST impedir hit em caches gerados sob política anterior.

#### Scenario: Cache miss após bump de política de diarização
- **WHEN** existe cache válido gerado sob política de diarização anterior para o mesmo modelo e texto
- **THEN** `interpret_chapter` NÃO reutiliza essa entrada

## MODIFIED Requirements

### Requirement: Interpretar capítulos via Ollama com JSON validado
O sistema SHALL enviar o texto de cada capítulo (ou de cada unidade de interpretação derivada do capítulo) a um backend LLM Ollama e SHALL aceitar apenas respostas JSON validadas por Pydantic (`LLMChapterResponse` ou equivalente) **e** aprovadas pelo gate de QA de diarização quando aplicável. O LLM MUST NÃO retornar texto livre interpretável ad-hoc. O modelo MUST ser configurável via CLI (`--model`), com default definido em configuração central (`qwen3:8b` recomendado). Esta change MUST NÃO exigir modelo maior que `qwen3:8b` para cumprir os requisitos de diarização e robustez.

#### Scenario: Resposta JSON válida
- **WHEN** Ollama retorna JSON que passa na validação Pydantic e no QA de diarização
- **THEN** o sistema produz a lista de diálogos/segmentos tipados para o capítulo (ou unidade)

#### Scenario: Resposta JSON inválida com retry
- **WHEN** a primeira resposta falha na validação Pydantic ou no parse JSON
- **THEN** o sistema registra o erro, solicita uma nova resposta incluindo o erro, e tenta validar novamente dentro do limite de tentativas configurado

#### Scenario: Falha após retry
- **WHEN** todas as tentativas configuradas permanecem inválidas (JSON, schema ou QA)
- **THEN** o sistema aborta o processamento do capítulo/unidade com erro contextual (capítulo, backend, motivo)

#### Scenario: Default Ollama é qwen3:8b
- **WHEN** o usuário executa `generate` sem `--model`
- **THEN** o backend LLM usa `qwen3:8b`

### Requirement: Contrato mínimo de saída narrativa
Cada resposta válida MUST incluir diálogos/segmentos com speaker (id ou nome resolvível), emotion (enum fechado) e text. Atualizações de história (`story_updates`) MUST ser mínimas e opcionalmente vazias. Emoções MUST pertencer ao conjunto padronizado: `neutral`, `happy`, `sad`, `angry`, `fear`, `excited`, `whisper`. Cada `dialogues[]` item MUST representar um único speaker; prosa narrativa (incluindo 1ª pessoa) MUST usar `narrator`; fala explícita do POV MUST usar o `character_id` do protagonista; falas de personagens distintos MUST NÃO compartilhar o mesmo item de diálogo.

#### Scenario: Diálogo com emoção válida
- **WHEN** o JSON contém um diálogo com emotion `angry` e texto não vazio
- **THEN** o modelo Pydantic aceita o diálogo

#### Scenario: Emoção fora do enum
- **WHEN** o JSON contém uma emotion não padronizada
- **THEN** a validação falha e o fluxo de retry/erro é acionado

#### Scenario: Um speaker por turno de fala
- **WHEN** o texto de origem contém fala de personagem A seguida de fala de personagem B
- **THEN** a resposta válida contém itens de diálogo distintos com speakers resolvíveis para A e B (não um único item misturando ambos)

#### Scenario: Fala do protagonista distinta da narração
- **WHEN** o capítulo tem prosa em 1ª pessoa e, em seguida, uma fala explícita do protagonista entre aspas
- **THEN** a prosa usa `narrator` e a fala usa o `character_id` do protagonista
