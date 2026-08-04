## Purpose

`ModelManager` centraliza download, validação e cache de pesos TTS (Qwen3-TTS) via Hugging Face, sem subprocess/CLI externa.

## Requirements

### Requirement: ModelManager centraliza pesos
O sistema SHALL expor um `ModelManager` no pacote `audiobook_ai.weights` responsável por verificar existência, baixar, validar arquivos necessários, reutilizar cache e expor paths de modelos lógicos. Backends TTS e Voice Design MUST obter paths apenas via o manager, não via download ad-hoc próprio. O registry MUST incluir o logical id `qwen3-tts` e MUST NÃO exigir pesos Fish Speech como dependência de produto.

#### Scenario: ensure_model qwen3-tts quando ausente
- **WHEN** `ensure_model("qwen3-tts")` é chamado e o modelo não está no cache
- **THEN** o manager baixa automaticamente via API Python do Hugging Face, armazena no diretório de cache e retorna/disponibiliza o path válido

#### Scenario: ensure_model quando presente e íntegro
- **WHEN** `ensure_model("qwen3-tts")` é chamado e os arquivos obrigatórios já existem e passam na validação
- **THEN** o manager NÃO baixa novamente e reutiliza o cache existente

#### Scenario: get_model
- **WHEN** `get_model("qwen3-tts")` é chamado após ensure bem-sucedido
- **THEN** retorna o path (ou handle tipado) apontando para o diretório/arquivos do modelo no cache

### Requirement: Diretório de cache com prioridade CLI > env > default
O diretório default de modelos MUST ser `~/.cache/audiobook-ai/` (subdirs por id lógico, ex.: `qwen3-tts/`). A resolução do root MUST seguir a prioridade: (1) argumento CLI `--cache-dir`, (2) variável de ambiente `AUDIOBOOK_AI_CACHE_DIR`, (3) default `~/.cache/audiobook-ai/`.

#### Scenario: Default XDG-style
- **WHEN** nenhum override de cache é fornecido
- **THEN** pesos são lidos/gravados sob `~/.cache/audiobook-ai/`

#### Scenario: Override via CLI
- **WHEN** o usuário passa `--cache-dir /caminho/customizado`
- **THEN** o manager usa `/caminho/customizado` mesmo que `AUDIOBOOK_AI_CACHE_DIR` esteja definida

#### Scenario: Override via env
- **WHEN** `--cache-dir` está ausente e `AUDIOBOOK_AI_CACHE_DIR` está definida
- **THEN** o manager usa o valor da variável de ambiente

### Requirement: Download sem subprocess ou CLI externa
Downloads MUST usar bibliotecas Python oficiais do Hugging Face (`huggingface_hub` ou equivalente suportado). O sistema MUST NÃO invocar `subprocess`, shell, `git clone`, `wget`, `curl`, ou CLI `hf` para obter pesos.

#### Scenario: Progresso de download
- **WHEN** um download longo está em andamento durante `ensure_model`
- **THEN** o manager expõe progresso consumível pela CLI (callback/eventos) sem usar `print()`

### Requirement: Revision pinada no registry do modelo
Cada definição de modelo no registry (incluindo `qwen3-tts`) MUST declarar revision pinada (tag ou commit SHA). Revision `main` ou branch flutuante MUST ser rejeitada na definição.

#### Scenario: Definição com main é inválida
- **WHEN** uma definição de peso tenta usar revision `main`
- **THEN** o registry/definição falha na construção ou validação

#### Scenario: Download reproduzível
- **WHEN** `ensure_model("qwen3-tts")` dispara um download
- **THEN** a chamada ao hub usa a `revision` pinada da definição do modelo, não `main`

### Requirement: Validação apenas dos arquivos necessários
Após o download, o manager MUST validar somente os arquivos necessários para inicializar o modelo (lista na definição versionada). Arquivos adicionais presentes no repositório HF MUST NÃO falhar a validação. Cache incompleto (faltando required) MUST disparar reparo/re-download, não load parcial silencioso.

#### Scenario: Cache incompleto
- **WHEN** o diretório do modelo existe mas faltam arquivos obrigatórios da definição
- **THEN** o manager trata como não pronto e completa/repara o download antes de sucesso

#### Scenario: Arquivos extras no repo
- **WHEN** o snapshot contém arquivos além da lista required
- **THEN** a validação passa se todos os required existem

### Requirement: Lock contra downloads simultâneos
O gerenciamento de pesos MUST usar um arquivo de lock no diretório de cache do modelo para que, se dois processos iniciarem `ensure_model` ao mesmo tempo, apenas um realize o download e o outro aguarde o lock e reutilize o modelo após a conclusão.

#### Scenario: Dois processos concorrentes
- **WHEN** dois processos chamam `ensure_model("qwen3-tts")` sem cache pronto
- **THEN** somente um processo baixa; o outro aguarda e ambos terminam com cache válido sem corrupção por escrita paralela

### Requirement: Falha de download Hugging Face é acionável
Se o download falhar por autenticação/rede, o sistema MUST falhar com mensagem acionável (auth HF / rede) sem traceback opaco como único sinal.

#### Scenario: Erro de acesso sem token
- **WHEN** `ensure_model` para `qwen3-tts` recebe erro de acesso/não autorizado do Hub
- **THEN** a falha reportada menciona login HF ou conectividade conforme aplicável
