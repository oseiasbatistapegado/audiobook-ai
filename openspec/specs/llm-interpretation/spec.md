## Purpose

Interpretar capítulos via Ollama com respostas JSON validadas por Pydantic e prompts externos ao código.

## Requirements

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

### Requirement: Prompts externos ao código
Os prompts de interpretação MUST residir em arquivos sob `llm/prompts/` e MUST NÃO ser strings hardcoded no código de chamada ao LLM.

#### Scenario: Carregamento de prompt
- **WHEN** o backend interpreta um capítulo
- **THEN** o texto do prompt é lido do arquivo de prompts correspondente

### Requirement: Prompt exige atribuição correta de speakers
O arquivo de prompt de interpretação sob `llm/prompts/` MUST instruir regras explícitas de diarização compatíveis com `qwen3:8b`: prosa narrativa (incluindo 1ª pessoa) MUST usar speaker `narrator`; fala explícita do POV/protagonista MUST usar o `character_id` do protagonista (não `narrator`); cada turno de fala MUST ter exatamente um speaker; MUST NÃO misturar falas de personagens distintos no mesmo `dialogues[].text`; speakers MUST ser escolhidos do speaker set fechado (`narrator` ∪ falantes do chapter cast da Pass 1); MUST NÃO inventar novos `speaker_id` fora desse conjunto; MUST NÃO usar mentioned-only como speaker; pistas de atribuição no texto-fonte MUST coincidir com o speaker do turno e MUST NÃO ser copiadas para dentro do `dialogues[].text` falado (a voz do turn identifica o falante); `narrator` MUST NÃO ser usado como fallback para fala não resolvida. O prompt MAY esclarecer que `speaker_id` identifica papel narrativo e NÃO implica por si só uma `voice_id` distinta.

#### Scenario: Prompt carrega regras de diarização
- **WHEN** o backend carrega o prompt de interpretação para uma chamada Ollama Pass 2
- **THEN** o texto do prompt inclui prosa/1ª pessoa → `narrator`, fala do POV → protagonist id, um speaker por turno, proibição de misturar falantes no mesmo `text`, proibição de speech-tags de atribuição no texto falado, speaker set fechado (só falantes), e proibição de `narrator` como fallback de diálogo

#### Scenario: Narração em 1ª pessoa não usa o protagonist id
- **WHEN** o texto é prosa em 1ª pessoa sem fala explícita entre aspas/travessão
- **THEN** a resposta válida atribui esse segmento a `narrator`, não ao `character_id` do protagonista

#### Scenario: Prompt lista speakers permitidos
- **WHEN** Pass 2 é invocada com chapter falantes `blond_boy` e `office_lady`
- **THEN** o contexto enviado ao modelo inclui esses ids (além de `narrator`) como speakers permitidos

### Requirement: Gate de QA semântica de diarização pós-schema

O QA SHALL operar por unidade individual e consumir `evidence.type` para decidir o **rigor de validação** (não apenas o gap de embedding):

|| evidence.type | Rigor do QA |
||---|---|
|| `EXPLICIT` | Skip (passa sem validação adicional) |
|| `TURN_ORDER` | Moderado (verifica alternância) |
|| `SCENE_CONTEXT` | Moderado |
|| `ALIAS_MATCH` | Moderado |
|| `EMBEDDING` | Rigoroso se gap ≤ `ATTRIBUTION_EMBEDDING_GAP_THRESHOLD` (default: `0.20`) |
|| `RELATIONSHIP` | Moderado |

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
### Requirement: Invariante de narração no QA de speakers
O checker de diarização MUST tratar turnos sem fala explícita (aspas/travessão/heurística de fala) cujo speaker não seja `narrator` como violação de narração, a menos que uma coerção determinística prévia já tenha corrigido o speaker para `narrator`. Isso MUST aplicar-se à prosa em primeira pessoa. A falha MUST ser reportada com prefixo identificável (ex. `speaker QA narration`).

#### Scenario: Prosa de 1ª pessoa no POV é rejeitada sem coerção
- **WHEN** um diálogo tem texto sem fala explícita e `speaker_id` igual ao protagonista e nenhuma coerção prévia foi aplicada
- **THEN** o checker falha com erro de narração

#### Scenario: Prosa atribuída a narrator passa
- **WHEN** um diálogo tem texto sem fala explícita e speaker `narrator`
- **THEN** o invariante de narração NÃO rejeita esse item por esse motivo

#### Scenario: Fala explícita do protagonista não é forçada a narrator
- **WHEN** um diálogo é fala explícita com `speaker_id` do protagonista
- **THEN** o invariante de narração NÃO rejeita esse item

### Requirement: Invariante de atribuição explícita no QA de speakers
O checker de diarização MUST detectar padrões de atribuição explícita no texto do próprio turno (ex. `“…” perguntou Horikita`, `Horikita respondeu: “…”`, `disse Sudou` ancorado à fala). Quando o nome/atributo resolve para um personagem conhecido no `story_state` e esse personagem diverge do speaker do turno, o checker MUST falhar com prefixo identificável (ex. `speaker QA attribution`). Se o nome atribuído NÃO resolve a um personagem conhecido, o checker MUST NÃO falhar somente por esse padrão.

#### Scenario: Fala com “perguntou Horikita” no POV é rejeitada
- **WHEN** o texto do turno contém fala explícita com atribuição resolvível a Horikita e o `speaker_id` é o protagonista
- **THEN** o checker falha com erro de atribuição

#### Scenario: Atribuição alinhada ao speaker passa
- **WHEN** o texto contém `respondeu Horikita` e o speaker do turno resolve para Horikita
- **THEN** o invariante de atribuição NÃO rejeita esse item

#### Scenario: Nome não resolvido não gera falso positivo
- **WHEN** o texto contém `disse AlguémDesconhecido` e esse nome não está no `story_state`
- **THEN** o invariante de atribuição NÃO falha apenas por esse padrão

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

### Requirement: Dominance permanece como rede de segurança
O detector de colapso global MUST permanecer ativo com os defaults de produto. O sistema MUST NÃO tratar a redução do threshold de dominance como substituto dos invariantes locais. A falha de dominance MUST usar prefixo identificável (ex. `speaker QA dominance`).

#### Scenario: ch-004 falha por invariante local com dominance baixa
- **WHEN** a fixture de regressão `ch-004` é avaliada e o `dominant_speaker_ratio` é inferior ao threshold de dominance
- **THEN** o checker ainda falha por narração e/ou atribuição (salvo coerção de narração já aplicada, restando atribuição quando aplicável)

#### Scenario: ch-011 continua rejeitado por dominance
- **WHEN** a fixture `ch-011` de colapso global é avaliada
- **THEN** o checker falha (por dominance e/ou outros invariantes aplicáveis)

### Requirement: QA de diarização separado de qualidade PT-BR
O checker de speakers MUST NÃO rejeitar respostas com base em qualidade de adaptação, calques, mistura de inglês, ou fluência do português brasileiro.

#### Scenario: Texto calque com speakers corretos passa no gate de speakers
- **WHEN** os diálogos têm speakers corretos segundo os invariantes mas o texto contém calque ou inglês residual
- **THEN** o checker de diarização NÃO falha por esse motivo

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


### Requirement: Política de cache inclui diarização/QA
A chave de cache de interpretação MUST incorporar um identificador estável da política de diarização/QA (além de locale/adaptação PT-BR, modelo, capítulo/unidade e payload). Alterar essa política MUST impedir hit em caches gerados sob política anterior. A introdução do strip/invariante de speech-tag MUST bump a versão de política de diarização (ex. `v5` → `v6`).

#### Scenario: Cache miss após bump de política de diarização
- **WHEN** existe cache válido gerado sob política de diarização anterior para o mesmo modelo e texto
- **THEN** `interpret_chapter` NÃO reutiliza essa entrada

#### Scenario: Cache miss após política v6 de speech-tag
- **WHEN** existe cache gerado sob `v5` (ou anterior) sem strip de speech-tag
- **THEN** a interpretação sob a nova política NÃO reutiliza essa entrada

### Requirement: Descarregar modelo Ollama sob pedido do pipeline
O `OllamaBackend` SHALL expor uma operação de unload (ex.: `unload`) que solicita ao servidor Ollama a liberação do modelo configurado da memória/VRAM do host (ex.: `keep_alive=0` ou API de stop equivalente). A operação MUST ser segura para chamar quando o modelo já não está carregado (idempotente ou no-op sem falha fatal). Chamadas de interpretação MUST poder solicitar que o modelo permaneça residente (`keep_alive=-1` ou equivalente) até o unload explícito do pipeline.

#### Scenario: Unload após interpretação
- **WHEN** o pipeline conclui `interpret_chapter` com chamada real ao Ollama e em seguida solicita unload
- **THEN** o backend solicita a liberação do modelo ao host Ollama configurado

#### Scenario: Unload com modelo já ausente
- **WHEN** unload é chamado e o modelo não está residente
- **THEN** o backend não aborta a geração por esse motivo

#### Scenario: Cache hit sem chamada Ollama
- **WHEN** `interpret_chapter` resolve por cache local sem chamar o servidor
- **THEN** o pipeline MAY omitir unload; se unload for chamado mesmo assim, MUST permanecer não-fatal

### Requirement: Texto falável em português brasileiro adaptado
O estágio de interpretação MUST produzir cada `dialogues[].text` em **português brasileiro** adequado a narração e fala em voz alta. O texto MUST ser uma **adaptação** do conteúdo do capítulo (qualquer idioma de origem), não uma tradução literal palavra a palavra: MUST preservar sentido, emoção e intenção, usando formulação natural em PT-BR. Nomes próprios e identificadores de personagem MUST permanecer estáveis quando forem identidades (salvo equivalente narrativo usual em PT-BR). Se o capítulo de origem já estiver em português brasileiro natural, o modelo MAY manter ou ajustar levemente o texto sem reescrita agressiva desnecessária. O sistema MUST NÃO introduzir um segundo passo LLM só para tradução/adaptação neste fluxo.

#### Scenario: Capítulo em idioma estrangeiro
- **WHEN** o backend interpreta um capítulo cujo texto de origem não está em português brasileiro
- **THEN** cada `dialogues[].text` na resposta validada está em português brasileiro adaptado (não calque literal) e permanece utilizável diretamente pelo TTS

#### Scenario: Capítulo já em PT-BR
- **WHEN** o backend interpreta um capítulo já escrito em português brasileiro natural
- **THEN** cada `dialogues[].text` permanece em português brasileiro natural, sem obrigação de reescrita substancial

#### Scenario: Sem passo extra de tradução
- **WHEN** o pipeline conclui `interpret_chapter` e segue para síntese TTS
- **THEN** o texto enviado ao TTS é o `dialogues[].text` da mesma resposta de interpretação (nenhuma segunda chamada LLM de tradução entre interpret e TTS)

### Requirement: Prompt declara política de adaptação PT-BR
O arquivo de prompt de interpretação sob `llm/prompts/` MUST instruir explicitamente a política de saída em português brasileiro adaptado (incluindo prosa de narrador e falas). A política MUST NÃO ficar apenas em comentários de código ou documentação externa ao prompt carregado.

#### Scenario: Prompt carrega regras de idioma
- **WHEN** o backend carrega o prompt de interpretação para uma chamada Ollama
- **THEN** o texto do prompt inclui a exigência de `dialogues[].text` em português brasileiro adaptado

### Requirement: Cache LLM invalida ao mudar política de adaptação
A chave de cache de interpretação MUST incorporar um identificador estável da política de saída/adaptação (por exemplo locale `pt-BR` + versão de política, ou hash/versão do prompt de sistema), além de modelo, capítulo, unidade e fingerprint estável de elenco — e MUST NÃO depender do JSON completo de `story_state`. Alterar a política de adaptação MUST impedir hit em entradas de cache geradas sob política anterior.

#### Scenario: Cache miss após mudança de política
- **WHEN** existe cache válido para o mesmo modelo, capítulo/unidade e fingerprint de elenco sob uma política de adaptação anterior, e a política atual difere
- **THEN** `interpret_chapter` NÃO reutiliza essa entrada e solicita nova interpretação (ou equivalente sem hit)

#### Scenario: Cache hit com mesma política
- **WHEN** existe cache válido gerado com a mesma política de adaptação, modelo, capítulo/unidade e fingerprint de elenco
- **THEN** `interpret_chapter` MAY reutilizar a entrada em cache

### Requirement: Chave de cache LLM estável ao crescimento do story
A chave de cache de interpretação MUST NÃO hashear o dump completo volátil de `story_state` (voice_map, ordem de serialização, perfis completos). MUST incorporar, além de modelo, `chapter_id`, índice/hash da unidade e identificadores de política de adaptação/diarização, um fingerprint estável do elenco conhecido (ex.: ids de personagens e aliases canônicos ordenados). O payload enviado ao Ollama MAY continuar incluindo o `story_state` completo para qualidade de diarização.

#### Scenario: Restart com story já populado reutiliza cache da mesma unidade
- **WHEN** existe cache válido para modelo, unidade (mesmo texto), políticas e fingerprint de elenco equivalentes, e o `story.json` no disco tem mais campos voláteis (ex.: voice_map atualizado) sem mudar o fingerprint de elenco
- **THEN** `interpret_chapter` MAY reutilizar a entrada em cache sem nova chamada Ollama

#### Scenario: Novo personagem no elenco invalida fingerprint
- **WHEN** o fingerprint de elenco difere do usado ao gravar o cache (novo `character_id` ou aliases relevantes)
- **THEN** o sistema NÃO reutiliza essa entrada de cache

### Requirement: voice_profile semântico opcional em story_updates
O contrato de interpretação MUST permitir que `story_updates.characters[]` incluam um objeto opcional `voice_profile` com hints semânticos para voice design (ex.: `gender`, `age_range`, `pitch`, `pace`, `energy`, `texture`, `personality`). A ausência de `voice_profile` MUST NÃO invalidar a resposta. O idioma canônico das vozes permanece `pt-BR`. O LLM MUST NÃO emitir parâmetros específicos de backend (Parler/Qwen/etc.); o adapter do `VoiceGenerator` traduz o perfil estruturado.

#### Scenario: Personagem com voice_profile
- **WHEN** o JSON válido inclui um personagem novo com `voice_profile.gender` e demais hints reconhecidos
- **THEN** o modelo Pydantic aceita a resposta e o pipeline pode repassar o perfil ao `VoiceGenerator` generativo

#### Scenario: Personagem sem voice_profile
- **WHEN** o JSON válido inclui um personagem sem campo `voice_profile`
- **THEN** a validação aceita o personagem e a geração usa defaults determinísticos + `character_id`/`book_id`

#### Scenario: Prompt documenta voice_profile sem APIs de backend
- **WHEN** o backend carrega o prompt de interpretação
- **THEN** o texto descreve o schema opcional de `voice_profile`, saída falável em pt-BR, e NÃO instrui o modelo a emitir parâmetros Parler/Qwen

### Requirement: Interpretação em duas passagens (cast então diarização)
Para cada capítulo, o backend LLM MUST (1) resolver o chapter cast via Pass 1 de cast discovery e (2) somente então interpretar cada unidade com Pass 2. Pass 2 MUST receber o speaker set fechado `narrator` ∪ ids classificados como falantes no chapter cast (`speaker` e, se existir, `possible_speaker`) e MUST NÃO descobrir novos `speaker_id` fora desse conjunto no mesmo passo de atribuição. Personagens mentioned-only MUST NÃO ser speakers válidos na Pass 2.

#### Scenario: Pass 2 vê speaker set fechado
- **WHEN** uma unidade é interpretada após Pass 1
- **THEN** o prompt/contexto de Pass 2 inclui a lista explícita de speaker ids permitidos derivados dos falantes do chapter cast (não dos mentioned-only)

#### Scenario: Mentioned-only excluído do speaker set
- **WHEN** Pass 1 classifica `manabu_horikita` como mentioned e `suzune_horikita` como speaker
- **THEN** o speaker set inclui `suzune_horikita` e `narrator`, e NÃO inclui `manabu_horikita`

#### Scenario: Speaker fora do conjunto rejeitado
- **WHEN** Pass 2 emite um `speaker_id` que não resolve para `narrator` nem para o speaker set do capítulo
- **THEN** a resposta falha validação/QA e entra no fluxo de retry (não é cacheada como sucesso)

### Requirement: Narrator não é fallback de incerteza
O prompt e o contrato de Pass 2 MUST tratar `narrator` como narração (incluindo prosa em 1ª pessoa sem fala explícita). Fala explícita / speech-like MUST ser atribuída a um membro do speaker set (ou ao id do protagonista quando for fala do POV), NÃO a `narrator` por incerteza. O sistema MUST NÃO converter silenciosamente diálogo de speaker desconhecido/omitido em `narrator`.

#### Scenario: Diálogo de personagem conhecido não vira narrator
- **WHEN** o speaker set contém `blond_boy` e o texto tem fala do garoto loiro
- **THEN** uma resposta válida atribui essa fala a `blond_boy` (ou alias resolvido), não a `narrator`

#### Scenario: Prosa em 1ª pessoa permanece narrator
- **WHEN** o turno é prosa reflexiva em 1ª pessoa sem fala explícita
- **THEN** o speaker permanece `narrator`

### Requirement: Pass 2 não cria personagens novos via story_updates de speakers
Pass 2 MUST NÃO introduzir novos personagens falantes em `story_updates.characters` como substituto da Pass 1. Atualizações mínimas de aliases MAY ser permitidas apenas para ids já presentes no chapter cast/story, se o schema atual exigir; a descoberta primária de novos falantes MUST ter ocorrido na Pass 1.

#### Scenario: story_updates de Pass 2 não inventa falante novo
- **WHEN** Pass 2 retorna JSON válido
- **THEN** nenhum `speaker_id` de diálogo depende de um personagem criado somente nessa resposta Pass 2 fora do chapter cast prévio

### Requirement: Gate de colapso de diálogo em narrator
Além do detector de dominance em speaker não-narrator, o checker de diarização MUST rejeitar o modo de falha em que há evidência de múltiplos falantes candidatos no speaker set/texto e a maior parte dos turnos speech-like está atribuída a `narrator`. A falha MUST usar prefixo identificável (ex. `speaker QA narrator-collapse`). O checker MUST NÃO exigir segundo modelo LLM. Limiares MUST ser configuráveis com defaults de produto documentados. A fixture de regressão derivada de `ch-005` (cena do ônibus) MUST ser coberta por teste obrigatório.

#### Scenario: Colapso em narrator rejeitado
- **WHEN** a unidade tem ≥2 falantes candidatos no speaker set, volume mínimo de turnos speech-like, e fração dominante desses turnos com speaker `narrator`
- **THEN** o checker falha com erro `narrator-collapse` e a resposta NÃO é aceita como interpretação final

#### Scenario: Monólogo sem multi-speaker passa
- **WHEN** o speaker set / evidência local não indica múltiplos falantes
- **THEN** o invariante de narrator-collapse NÃO rejeita só porque há muitos turnos `narrator`

#### Scenario: Fixture ch-005 rejeita colapso conhecido
- **WHEN** o checker recebe a fixture de regressão derivada do `ch-005` com falas de `blond_boy`/`elderly_woman`/schoolgirl colapsadas em `narrator`
- **THEN** o checker falha

### Requirement: Retry de narrator-collapse sem refresh de Pass 1
Quando o gate de narrator-collapse falha, o MVP MUST retentar apenas a Pass 2 com o **mesmo** chapter cast / speaker set fechado, incluindo o erro de QA e instrução de correção de atribuição. O MVP MUST NÃO invalidar automaticamente nem reexecutar Pass 1 por causa de narrator-collapse. Refresh automático de cast discovery após falha de diarização fica explicitamente fora do MVP. Se as tentativas Pass 2 se esgotarem, o sistema MUST abortar a unidade com a semântica de falha de interpretação já existente.

#### Scenario: Narrator-collapse retenta Pass 2 com o mesmo cast
- **WHEN** Pass 2 falha com `speaker QA narrator-collapse`
- **THEN** a próxima tentativa Pass 2 reutiliza o mesmo speaker set fechado e inclui o feedback de QA

#### Scenario: Narrator-collapse não dispara Pass 1
- **WHEN** ocorre narrator-collapse durante Pass 2
- **THEN** o sistema NÃO reexecuta cast discovery automaticamente nessa falha

#### Scenario: Retries esgotados abortam a unidade
- **WHEN** todas as tentativas Pass 2 após narrator-collapse continuam inválidas
- **THEN** o processamento da unidade aborta com erro contextual (sem aceitar o colapso)

### Requirement: Política de cache/diarização bumpada para two-pass
A versão de política de diarização MUST ser incrementada de forma que caches de interpretação single-pass anteriores NÃO sejam reutilizados como sucesso sob a arquitetura two-pass.

#### Scenario: Cache single-pass antigo não é hit
- **WHEN** existe cache de interpret gerado sob política anterior à two-pass
- **THEN** a execução atual com a nova política NÃO trata esse cache como resposta válida de Pass 2
