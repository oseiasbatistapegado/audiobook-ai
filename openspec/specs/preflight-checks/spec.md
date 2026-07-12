## Purpose

Checagens antecipadas (ffmpeg, Ollama/modelo LLM, imports TTS) antes do trabalho pesado do pipeline `generate`.

## Requirements

### Requirement: Verificar ffmpeg antes do pipeline
Antes de iniciar extração/interpretação/TTS, o sistema SHALL verificar se `ffmpeg` está disponível no PATH. Se ausente, MUST abortar imediatamente com mensagem acionável (ex.: entrar no devShell/direnv ou instalar ffmpeg).

#### Scenario: ffmpeg ausente no início
- **WHEN** o usuário executa `audiobook-ai generate` e `ffmpeg` não está no PATH
- **THEN** a CLI falha cedo com código diferente de zero e mensagem que indica como obter ffmpeg, sem baixar pesos TTS nem chamar Ollama para o livro inteiro

### Requirement: Verificar Ollama e modelo LLM antes do pipeline
Antes do trabalho pesado do pipeline, o sistema SHALL verificar que o host Ollama configurado está alcançável e que o modelo LLM selecionado (`--model` ou default) está disponível. Se a checagem falhar, MUST abortar com mensagem que indique correção (ex.: iniciar Ollama, `ollama pull <model>`).

#### Scenario: Ollama inacessível
- **WHEN** o host Ollama não responde
- **THEN** a CLI falha cedo com erro contextual incluindo o host tentado

#### Scenario: Modelo LLM ausente
- **WHEN** Ollama responde mas o modelo configurado não está instalado
- **THEN** a CLI falha cedo sugerindo puxar/instalar o modelo nomeado

### Requirement: Verificar imports do runtime TTS
Quando o backend TTS for Fish Speech in-process, o preflight SHALL verificar que `torch` e `fish_speech` são importáveis. Se ausentes, MUST falhar com a sequência de instalação documentada (extra `tts-fish` + pacote fish-speech), sem iniciar download de pesos.

#### Scenario: fish_speech não instalado
- **WHEN** `import fish_speech` falha no preflight
- **THEN** a CLI aborta com instruções de install e não chama `ModelManager.ensure_model`

### Requirement: Preflight valida o default qwen3:8b
Quando o usuário não sobrescreve `--model`, a checagem de preflight MUST exigir que `qwen3:8b` esteja disponível no host Ollama configurado (mesma regra de disponibilidade já usada para modelos nomeados).

#### Scenario: Default ausente no Ollama
- **WHEN** o preflight roda sem `--model` e `qwen3:8b` não está instalado
- **THEN** a CLI falha cedo sugerindo `ollama pull qwen3:8b`
