## MODIFIED Requirements

### Requirement: Interpretar capítulos via Ollama com JSON validado
O sistema SHALL enviar o texto de cada capítulo a um backend LLM Ollama em **duas etapas LLM separadas por cena**: (1) **Speaker Attribution** que recebe unidades agrupadas por cena, classifica o autor com `primary`, `ranked_candidates`, e `evidence` tipada; e (2) **Interpretação** que gera o JSON final com emoções e tradução, recebendo `speaker_id` já resolvido. O LLM MUST NÃO retornar texto livre interpretável ad-hoc. O modelo MUST ser configurável via CLI (`--model`), com default definido em configuração central (`qwen3:8b` recomendado).

**A primeira etapa (Attribution)** recebe como input: unidades agrupadas por cena, o `candidate_set` do `CandidateGenerator` (candidatos já resolvidos por código), e os `character_profiles` (imutáveis). A Attribution é uma etapa de **classificação**, não de geração criativa.

**A segunda etapa (Interpretação)** recebe como input **apenas**: `speaker_id` (já resolvido), `emotion_constraints` (enum fechado), `adaptation_policy` (version hash + regras pt-BR), e `unit_text`. Todo o contexto de personagem, scene graph, conversation state, aliases, relationships, speaking style, role **NÃO** é enviado — já foi resolvido.

#### Scenario: Resposta JSON válida
- **WHEN** Ollama retorna JSON que passa na validação Pydantic e no QA de diarização
- **THEN** o sistema produz a lista de diálogos/segmentos tipados para o capítulo (ou unidade)

#### Scenario: Resposta JSON inválida com retry
- **WHEN** a primeira resposta falha na validação Pydantic ou no parse JSON
- **THEN** o sistema registra o erro, solicita uma nova resposta incluindo o erro, e tenta validar novamente dentro do limite de tentativas configurado

#### Scenario: Falha após retry — unidade com status needs_review
- **WHEN** todas as tentativas configuradas permanecem inválidas (JSON, schema ou QA)
- **THEN** o sistema marca a **unidade** com `status: "needs_review"`, `speaker_id: null`, `text: original_text`, `emotion: "neutral"`, `rejection_reason: "..."` e **continua** processando as demais unidades do capítulo

#### Scenario: Default Ollama é qwen3:8b
- **WHEN** o usuário executa `generate` sem `--model`
- **THEN** o backend LLM usa `qwen3:8b`

#### Scenario: Duas chamadas LLM por cena
- **WHEN** um capítulo com 120 unidades (8 cenas) é interpretado
- **THEN** são feitas 8 chamadas Attribution (uma por cena) + 8 chamadas Interpretation (uma por cena), total de 16 chamadas (não 120 + 120)

#### Scenario: Interpretação recebe input mínimo
- **WHEN** a Interpretation Pass é invocada
- **THEN** o user payload contém apenas `speaker_id` + `emotion_constraints` + `adaptation_policy` + `unit_text` (sem perfis, sem scene graph, sem aliases, sem relationships)

### Requirement: Gate de QA semântica de diarização pós-schema

O QA SHALL operar por unidade individual e consumir `evidence.type` para decidir o **rigor de validação** (não apenas o gap de embedding):

| evidence.type | Rigor do QA |
|---|---|
| `EXPLICIT` | Skip (passa sem validação adicional) |
| `TURN_ORDER` | Moderado (verifica alternância) |
| `SCENE_CONTEXT` | Moderado |
| `ALIAS_MATCH` | Moderado |
| `EMBEDDING` | Rigoroso se gap ≤ `ATTRIBUTION_EMBEDDING_GAP_THRESHOLD` (default: `0.20`) |
| `RELATIONSHIP` | Moderado |

Se a resposta falha no checker, a unidade **única** deve entrar no fluxo de retry com mensagem de erro acionável. O checker NÃO exige um segundo modelo LLM. Defaults de produto: `LLM_SPEAKER_QA_MIN_QUOTED_TURNS=6`, `LLM_SPEAKER_QA_DOMINANCE_THRESHOLD=0.85`. O detector de colapso global falha quando simultaneamente: `quoted_turns >= LLM_SPEAKER_QA_MIN_QUOTED_TURNS` AND `dominant_speaker_ratio >= LLM_SPEAKER_QA_DOMINANCE_THRESHOLD` AND `evidence_of_multiple_speakers >= 2`. `evidence_of_multiple_speakers` considera personagens conhecidos no `story_state` e atribuições explícitas locais. O caso de regressão `ch-011` é coberto por fixture obrigatória. O caso de regressão de speech-tag `ch-004` é coberto por fixture obrigatória.

#### Scenario: Evidence EXPLICIT pula validação adicional
- **WHEN** a unidade tem evidence `{"type": "EXPLICIT", "detail": "disse Horikita"}`
- **THEN** o QA **não** aplica invariantes adicionais (passa direto)

#### Scenario: Colapso de speakers em turnos falados rejeitado
- **WHEN** uma resposta schema-válida tem `quoted_turns >= 6`, `dominant_speaker_ratio >= 0.85` para um speaker não-`narrator`, e `evidence_of_multiple_speakers >= 2`
- **THEN** o checker falha, e o backend solicita nova tentativa **para aquela unidade** incluindo o erro de QA

#### Scenario: Monólogo sem múltiplos falantes passa no QA
- **WHEN** uma resposta schema-válida tem `quoted_turns < 6` ou `evidence_of_multiple_speakers < 2`
- **THEN** o checker NÃO rejeita apenas por baixa diversidade de `speaker_id`

#### Scenario: QA failure não grava cache de sucesso
- **WHEN** a resposta falha no checker de diarização
- **THEN** o backend NÃO grava essa resposta no cache de interpretação como sucesso

#### Scenario: Evidence EMBEDDING com gap ≤ 0.20 aciona QA rigoroso
- **WHEN** a unidade tem evidence `{"type": "EMBEDDING", "detail": "gap=0.03"}`
- **THEN** o QA aplica todos os invariantes sem atenuantes

#### Scenario: Fixture ch-011 rejeita colapso conhecido
- **WHEN** o checker recebe a fixture de regressão derivada do `ch-011` com falas de Sudou/Ike/Yamauchi atribuídas ao protagonista
- **THEN** o checker falha

#### Scenario: Fixture ch-004 speech-tag é coberta pelo pipeline
- **WHEN** a fixture de speech-tag derivada de `ch-004` é processada pelo fluxo repair+checker
- **THEN** ou o strip remove as tags e a resposta passa no invariante de speech-tag, ou tags residuais fazem o checker falhar

#### Scenario: Falha de QA em unidade é isolada
- **WHEN** uma unidade falha no QA e é reprocessada
- **THEN** as demais unidades do capítulo não são afetadas

#### Scenario: Unidade após esgotar retries recebe status: needs_review
- **WHEN** todas as tentativas configuradas (`QA_CORRECTION_MAX_ATTEMPTS`) falham no QA
- **THEN** a unidade é mantida com `{status: "needs_review", speaker_id: null, text: original, emotion: "neutral", rejection_reason: "..."}`
- **THEN** o downstream TTS omite o segmento do merge de áudio

### Requirement: Retries cobrem JSON, schema e QA
O backend de interpretação permite até `LLM_INTERPRET_MAX_ATTEMPTS` tentativas por unidade, default `3`. Falhas de parse JSON, validação Pydantic e QA consomem tentativas e incluem o erro específico na mensagem de retry. Após esgotar as tentativas, o sistema **marca a unidade com `status: "needs_review"`** (`speaker_id: null`, `text: original_text`, `emotion: "neutral"`, `rejection_reason: "..."`) e **continua** processando as demais unidades. O sistema aplica reparo mecânico mínimo de JSON (ex.: trailing commas) antes de declarar falha de parse, sem inventar conteúdo narrativo.

#### Scenario: Terceira tentativa recupera após QA
- **WHEN** as duas primeiras respostas falham no QA de diarização e a terceira passa schema + QA
- **THEN** o backend aceita a terceira resposta e pode cacheá-la como sucesso

#### Scenario: Esgotamento de tentativas marca unidade com needs_review
- **WHEN** todas as tentativas configuradas falham por JSON, schema ou QA
- **THEN** o sistema marca a unidade com `status: "needs_review"`, continua processando o capítulo, e emite log de warning

#### Scenario: Unidade needs_review é omitida pelo downstream TTS
- **WHEN** uma unidade tem `status: "needs_review"`
- **THEN** a fase TTS omite este segmento do merge final (não gera audio)

### Requirement: Caches separados de attribution e interpretação

O sistema mantém dois caches independentes com chaves keyed por **cena** (não por capítulo):

**Attribution cache key:** `scene_hash + character_profile_hash + candidate_generator_version + attribution_policy_version`

**Interpretation cache key:** `scene_hash + attribution_cache_key + prompt_version + adaptation_policy_version`

Bump de versão em qualquer um dos caches invalida automaticamente os entries daquele cache específico.

#### Scenario: Bump de attribution invalida apenas attribution cache
- **WHEN** a política de attribution muda
- **THEN** caches de attribution são invalidados, caches de interpretação permanecem válidos

#### Scenario: Bump de interpretação invalida apenas interpretação cache
- **WHEN** o prompt de interpretação muda
- **THEN** caches de interpretação são invalidados, caches de attribution permanecem válidos

#### Scenario: Cache keyed por cena (não por capítulo)
- **WHEN** uma cena é processada
- **THEN** o attribution cache e interpretation cache são keyed por `scene_hash` (não `chapter_hash`)
