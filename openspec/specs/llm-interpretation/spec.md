## Purpose

Interpretar capítulos via Ollama com respostas JSON validadas por Pydantic e prompts externos ao código.

## Requirements

### Requirement: Interpretar capítulos via Ollama com JSON validado
O sistema SHALL enviar o texto de cada capítulo a um backend LLM Ollama e SHALL aceitar apenas respostas JSON validadas por Pydantic (`LLMChapterResponse` ou equivalente). O LLM MUST NÃO retornar texto livre interpretável ad-hoc. O modelo MUST ser configurável via CLI (`--model`), com default definido em configuração central (`qwen3:8b` recomendado).

#### Scenario: Resposta JSON válida
- **WHEN** Ollama retorna JSON que passa na validação Pydantic
- **THEN** o sistema produz a lista de diálogos/segmentos tipados para o capítulo

#### Scenario: Resposta JSON inválida com retry
- **WHEN** a primeira resposta falha na validação Pydantic
- **THEN** o sistema registra o erro, solicita uma nova resposta incluindo o erro de schema, e tenta validar novamente

#### Scenario: Falha após retry
- **WHEN** a segunda resposta também é inválida
- **THEN** o sistema aborta o processamento do capítulo com erro contextual (capítulo, backend, motivo)

#### Scenario: Default Ollama é qwen3:8b
- **WHEN** o usuário executa `generate` sem `--model`
- **THEN** o backend LLM usa `qwen3:8b`

### Requirement: Contrato mínimo de saída narrativa
Cada resposta válida MUST incluir diálogos/segmentos com speaker (id ou nome resolvível), emotion (enum fechado) e text. Atualizações de história (`story_updates`) MUST ser mínimas e opcionalmente vazias. Emoções MUST pertencer ao conjunto padronizado: `neutral`, `happy`, `sad`, `angry`, `fear`, `excited`, `whisper`.

#### Scenario: Diálogo com emoção válida
- **WHEN** o JSON contém um diálogo com emotion `angry` e texto não vazio
- **THEN** o modelo Pydantic aceita o diálogo

#### Scenario: Emoção fora do enum
- **WHEN** o JSON contém uma emotion não padronizada
- **THEN** a validação falha e o fluxo de retry/erro é acionado

### Requirement: Prompts externos ao código
Os prompts de interpretação MUST residir em arquivos sob `llm/prompts/` e MUST NÃO ser strings hardcoded no código de chamada ao LLM.

#### Scenario: Carregamento de prompt
- **WHEN** o backend interpreta um capítulo
- **THEN** o texto do prompt é lido do arquivo de prompts correspondente

### Requirement: Descarregar modelo Ollama sob pedido do pipeline
O `OllamaBackend` SHALL expor uma operação de unload (ex.: `unload`) que solicita ao servidor Ollama a liberação do modelo configurado da memória/VRAM do host (ex.: `keep_alive=0` ou API de stop equivalente). A operação MUST ser segura para chamar quando o modelo já não está carregado (idempotente ou no-op sem falha fatal).

#### Scenario: Unload após interpretação
- **WHEN** o pipeline conclui `interpret_chapter` com chamada real ao Ollama e em seguida solicita unload
- **THEN** o backend solicita a liberação do modelo ao host Ollama configurado

#### Scenario: Unload com modelo já ausente
- **WHEN** unload é chamado e o modelo não está residente
- **THEN** o backend não aborta a geração por esse motivo

#### Scenario: Cache hit sem chamada Ollama
- **WHEN** `interpret_chapter` resolve por cache local sem chamar o servidor
- **THEN** o pipeline MAY omitir unload; se unload for chamado mesmo assim, MUST permanecer não-fatal

### Requirement: Descarregar modelo Ollama sob pedido do pipeline
O `OllamaBackend` SHALL expor uma operação de unload (ex.: `unload`) que solicita ao servidor Ollama a liberação do modelo configurado da memória/VRAM do host (ex.: `keep_alive=0` ou API de stop equivalente). A operação MUST ser segura para chamar quando o modelo já não está carregado (idempotente ou no-op sem falha fatal).

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
A chave de cache de interpretação MUST incorporar um identificador estável da política de saída/adaptação (por exemplo locale `pt-BR` + versão de política, ou hash/versão do prompt de sistema), além de modelo, capítulo e payload do usuário. Alterar a política de adaptação MUST impedir hit em entradas de cache geradas sob política anterior.

#### Scenario: Cache miss após mudança de política
- **WHEN** existe cache válido para o mesmo modelo, capítulo e payload sob uma política de adaptação anterior, e a política atual difere
- **THEN** `interpret_chapter` NÃO reutiliza essa entrada e solicita nova interpretação (ou equivalente sem hit)

#### Scenario: Cache hit com mesma política
- **WHEN** existe cache válido gerado com a mesma política de adaptação, modelo, capítulo e payload
- **THEN** `interpret_chapter` MAY reutilizar a entrada em cache

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
