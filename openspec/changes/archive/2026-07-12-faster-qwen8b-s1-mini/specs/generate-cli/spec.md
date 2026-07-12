## ADDED Requirements

### Requirement: Default de --model na CLI é qwen3:8b
Quando `--model` é omitido, a CLI `generate` MUST usar o default centralizado `qwen3:8b` para o backend Ollama.

#### Scenario: Generate sem --model
- **WHEN** o usuário executa `audiobook-ai generate <pdf>` sem `--model`
- **THEN** o pipeline interpreta capítulos com `qwen3:8b`

### Requirement: Opção --fish-model para pesos Fish open
A CLI `generate` MUST expor `--fish-model` (e MAY aceitar env `AUDIOBOOK_AI_FISH_MODEL`) para selecionar um alias de pesos Fish **open** registrado no ModelManager. O default MUST ser `s1-mini`. Aliases MVP MUST incluir `s1-mini` e `s2-pro`. Valor desconhecido MUST falhar cedo com a lista dos aliases válidos. Esta opção MUST NÃO alterar o modelo Ollama (`--model`).

#### Scenario: Default fish-model é s1-mini
- **WHEN** o usuário executa `generate` sem `--fish-model` e sem env override
- **THEN** o pipeline assegura/carrega os pesos do alias `s1-mini`

#### Scenario: Override para s2-pro
- **WHEN** o usuário passa `--fish-model s2-pro`
- **THEN** o pipeline assegura/carrega os pesos do alias `s2-pro` e não o S1-mini

#### Scenario: Alias inválido
- **WHEN** o usuário passa `--fish-model` com um valor não registrado
- **THEN** a CLI falha cedo listando os aliases válidos (incluindo `s1-mini` e `s2-pro`)
