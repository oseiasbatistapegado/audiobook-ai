## ADDED Requirements

### Requirement: ModelManager centraliza pesos
O sistema SHALL expor um `ModelManager` no pacote `audiobook_ai.weights` (`manager.py`, com suporte em `cache.py` e definições por backend ex. `fish.py`) responsável por verificar existência, baixar, validar arquivos necessários, reutilizar cache e expor paths de modelos lógicos (ex.: `fish-speech`). Backends TTS MUST obter paths apenas via o manager, não via download ad-hoc próprio.

#### Scenario: ensure_model quando ausente
- **WHEN** `ensure_model("fish-speech")` é chamado e o modelo não está no cache
- **THEN** o manager baixa automaticamente via API Python do Hugging Face, armazena no diretório de cache e retorna/disponibiliza o path válido

#### Scenario: ensure_model quando presente e íntegro
- **WHEN** `ensure_model("fish-speech")` é chamado e os arquivos obrigatórios já existem e passam na validação
- **THEN** o manager NÃO baixa novamente e reutiliza o cache existente

#### Scenario: get_model
- **WHEN** `get_model("fish-speech")` é chamado após ensure bem-sucedido
- **THEN** retorna o path (ou handle tipado) apontando para o diretório/arquivos do modelo no cache

### Requirement: Diretório de cache com prioridade CLI > env > default
O diretório default de modelos MUST ser `~/.cache/audiobook-ai/` (subdirs por id lógico, ex.: `fish-speech/`). A resolução do root MUST seguir a prioridade: (1) argumento CLI `--cache-dir`, (2) variável de ambiente `AUDIOBOOK_AI_CACHE_DIR`, (3) default `~/.cache/audiobook-ai/`.

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
Cada modelo lógico (ex.: Fish Speech) MUST ser definido com `repository` e `revision` (tag ou commit) versionados no código/config. O sistema MUST NÃO baixar da branch flutuante `main`.

#### Scenario: Download reproduzível
- **WHEN** `ensure_model("fish-speech")` dispara um download
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
- **WHEN** dois processos chamam `ensure_model("fish-speech")` sem cache pronto
- **THEN** somente um processo baixa; o outro aguarda e ambos terminam com cache válido sem corrupção por escrita paralela
