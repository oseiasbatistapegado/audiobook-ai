## MODIFIED Requirements

### Requirement: Transições de handoff por fases GPU
O pipeline MUST orquestrar fases com hard reclaim verificado entre backends GPU incompatíveis: liberar TTS antes de interpret quando necessário; descarregar Ollama antes de Voice Design/TTS; Voice Design → verificar release → fase TTS. A arquitetura MUST favorecer **Interpretation Phase → TTS Phase contínua → Merge** para amortizar load/init/caches do Qwen3-TTS. Manter o engine TTS carregado entre capítulos/chunks da fase TTS contínua MUST ser o comportamento preferido quando o guardian não sinalizar pressão real. Restart controlado do worker permanece permitido.

#### Scenario: Sequência interpretation então TTS contínua
- **WHEN** um livro requer interpretação de vários capítulos e síntese TTS
- **THEN** o pipeline completa a interpretação (e Voice Design necessário) antes de uma fase TTS contínua que drena SpeechChunks pendentes sem reload por capítulo

#### Scenario: Voice Design antes da fase TTS
- **WHEN** um livro requer Voice Design e síntese TTS
- **THEN** o Voice Design worker termina e a liberação de VRAM é verificada antes do worker TTS iniciar

#### Scenario: Restart de worker entre chunks
- **WHEN** o worker TTS encerra de forma controlada com SpeechChunks ainda pendentes
- **THEN** o orquestrador MAY iniciar um novo worker para continuar sem violar o lease único

#### Scenario: Liberação antes de novo interpret
- **WHEN** a fase TTS termina e uma nova interpretação remota é necessária
- **THEN** nenhum worker TTS está ativo antes do interpret
