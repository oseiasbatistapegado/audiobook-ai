## Purpose

Checagens antecipadas (ffmpeg, Ollama/modelo LLM, imports TTS) antes do trabalho pesado do pipeline `generate`.

## Requirements

### Requirement: Verificar ffmpeg antes do pipeline
Antes de iniciar extração/interpretação/TTS, o sistema SHALL verificar se `ffmpeg` está disponível no PATH. Se ausente, MUST abortar imediatamente com mensagem acionável (ex.: entrar no devShell/direnv ou instalar ffmpeg).

#### Scenario: ffmpeg ausente no início
- **WHEN** o usuário executa `audiobook-ai generate` e `ffmpeg` não está no PATH
- **THEN** a CLI falha cedo com código diferente de zero e mensagem que indica como obter ffmpeg, sem baixar pesos TTS nem chamar Ollama para o livro inteiro

### Requirement: Verificar Ollama e modelo LLM antes do pipeline
Antes do trabalho pesado do pipeline, o sistema SHALL verificar que o host do llama-server configurado está alcançável (via `GET /health` ou `GET /v1/models`) e que o modelo LLM selecionado (`--model` ou default) está disponível no servidor. Se a checagem falhar, MUST abortar com mensagem que indique correção (ex.: iniciar `llama-server`, verificar `--model`).

#### Scenario: llama-server inacessível
- **WHEN** o host do llama-server não responde
- **THEN** a CLI falha cedo com erro contextual incluindo o host tentado

#### Scenario: Modelo LLM ausente
- **WHEN** llama-server responde mas o modelo configurado não está carregado
- **THEN** a CLI falha cedo sugerindo verificar o modelo carregado

### Requirement: Verificar imports do runtime TTS
Quando o backend TTS for Qwen3-TTS, o preflight SHALL verificar que o runtime necessário (`torch` e o pacote `qwen_tts` / equivalente pinado) é importável. Se ausente, MUST falhar com a sequência de instalação documentada do extra TTS Qwen3, sem iniciar download de pesos. O preflight MUST NÃO exigir `fish_speech`.

#### Scenario: qwen_tts não instalado
- **WHEN** `import qwen_tts` (ou equivalente documentado) falha no preflight
- **THEN** a CLI aborta com instruções de install e não chama `ModelManager.ensure_model` para TTS

#### Scenario: fish_speech não é requisito
- **WHEN** `fish_speech` não está instalado mas o runtime Qwen3-TTS está importável
- **THEN** o preflight TTS NÃO falha por ausência de Fish

### Requirement: Preflight valida independência Parler/DAC sem Fish
Quando Voice Design Parler estiver habilitado no caminho de produto, o preflight (ou teste de instalação documentado) SHALL verificar que as dependências de decode necessárias ao Parler estão disponíveis sem exigir `fish-speech`.

#### Scenario: Parler ready sem Fish
- **WHEN** o preflight/checagem de Voice Design roda com Parler instalado e `fish-speech` ausente
- **THEN** a checagem de dependências de codec/DAC do Parler passa ou falha com instrução de install do extra Parler autossuficiente (nunca “instale fish-speech”)

### Requirement: Preflight valida o default qwen3:8b
Quando o usuário não sobrescreve `--model`, a checagem de preflight MUST exigir que `qwen3:8b` esteja disponível no host do llama-server configurado (mesma regra de disponibilidade já usada para modelos nomeados).

#### Scenario: Default ausente no llama-server
- **WHEN** o preflight roda sem `--model` e `qwen3:8b` não está carregado
- **THEN** a CLI falha cedo com instrução para iniciar o server com o modelo correto
