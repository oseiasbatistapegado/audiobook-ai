## MODIFIED Requirements

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

### Requirement: Revision pinada no registry do modelo
Cada definição de modelo no registry (incluindo `qwen3-tts`) MUST declarar revision pinada (tag ou commit SHA). Revision `main` ou branch flutuante MUST ser rejeitada na definição.

#### Scenario: Definição com main é inválida
- **WHEN** uma definição de peso tenta usar revision `main`
- **THEN** o registry/definição falha na construção ou validação

## REMOVED Requirements

### Requirement: Registry de pesos Fish open por alias
**Reason:** Aliases Fish `s1-mini` / `s2-pro` removidos do produto.
**Migration:** Usar logical id único `qwen3-tts` com repository/revision pinados em `weights/qwen3_tts.py`.

### Requirement: Falha gated Hugging Face é acionável
**Reason:** Texto/gated hint específico do Fish (`openaudio-s1-mini`) deixa de aplicar; Qwen3-TTS Base não usa esse fluxo gated.
**Migration:** Mensagens de falha de download MUST permanecer acionáveis de forma genérica (auth HF / rede) sem instruções Fish.
