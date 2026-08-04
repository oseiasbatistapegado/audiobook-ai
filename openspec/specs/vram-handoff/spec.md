## Purpose

Orquestrar exclusão mútua de VRAM entre LLM (Ollama), Voice Design e TTS no pipeline `generate`, com handoff por fases GPU, workers isolados e progresso visível.

## Requirements

### Requirement: Exclusão mútua de VRAM entre LLM e TTS
O pipeline `generate` SHALL garantir que nenhum worker/engine TTS esteja residente na GPU durante a fase `interpret` (Ollama) e que o modelo Ollama não esteja residente na memória/VRAM do host durante a fase TTS, quando ambos os backends estiverem em uso. Voice Design e a fase TTS MUST NÃO estar ativos simultaneamente. Ollama e Voice Design MUST NÃO estar ativos simultaneamente na GPU.

#### Scenario: Interpret com TTS liberado
- **WHEN** o pipeline inicia a interpretação de um capítulo
- **THEN** nenhum worker TTS está ativo (e o orquestrador não mantém engine TTS carregado)

#### Scenario: TTS com Ollama liberado
- **WHEN** o pipeline inicia a fase TTS após o interpret
- **THEN** o modelo Ollama foi descarregado (`unload`) antes do spawn/load do worker TTS

#### Scenario: Voice Design com Ollama liberado
- **WHEN** o pipeline inicia Voice Design na GPU
- **THEN** o modelo Ollama foi descarregado antes do worker de Voice Design

### Requirement: Transições de handoff por fases GPU
O pipeline MUST orquestrar fases com hard reclaim verificado entre backends GPU incompatíveis: liberar TTS antes de interpret quando necessário; descarregar Ollama antes de Voice Design quando houver trabalho de Voice Design na GPU e antes da fase TTS contínua; Voice Design → verificar release → fase TTS. Durante o Pass A, o sistema MUST NÃO descarregar o Ollama após cada capítulo apenas por rotina: unload entre capítulos do Pass A MUST ocorrer somente quando o próximo uso da GPU for Voice Design (personagens sem voz a gerar) ou quando se inicia a fase TTS. A arquitetura MUST favorecer **Interpretation Phase → TTS Phase contínua → Merge** para amortizar load/init/caches do Qwen3-TTS. Manter o engine TTS carregado entre capítulos/chunks da fase TTS contínua MUST ser o comportamento preferido quando o guardian não sinalizar pressão real. Restart controlado do worker permanece permitido.

#### Scenario: Sequência interpretation então TTS contínua
- **WHEN** um livro requer interpretação de vários capítulos e síntese TTS
- **THEN** o pipeline completa a interpretação (e Voice Design necessário) antes de uma fase TTS contínua que drena SpeechChunks pendentes sem reload por capítulo

#### Scenario: Capítulos consecutivos sem Voice Design mantêm Ollama
- **WHEN** dois capítulos seguidos no Pass A usam Ollama remoto e o segundo não requer Voice Design GPU imediatamente após o primeiro
- **THEN** o pipeline NÃO solicita unload do Ollama só por ter terminado o primeiro capítulo

#### Scenario: Voice Design força unload do Ollama
- **WHEN** após interpretar um capítulo existem personagens que precisam de Voice Design na GPU
- **THEN** o Ollama é descarregado e a liberação de VRAM é verificada antes do worker de Voice Design

#### Scenario: Voice Design antes da fase TTS
- **WHEN** um livro requer Voice Design e síntese TTS
- **THEN** o Voice Design worker termina e a liberação de VRAM é verificada antes do worker TTS iniciar

#### Scenario: Restart de worker entre chunks
- **WHEN** o worker TTS encerra de forma controlada com SpeechChunks ainda pendentes
- **THEN** o orquestrador MAY iniciar um novo worker para continuar sem violar o lease único

#### Scenario: Liberação antes de novo interpret
- **WHEN** a fase TTS termina e uma nova interpretação remota é necessária
- **THEN** nenhum worker TTS está ativo antes do interpret

### Requirement: Progresso visível do handoff
O pipeline SHALL notificar progresso (callback / Rich) e registrar log quando executar unload de Ollama, spawn/exit de workers GPU, verificação de release de VRAM, ou restart controlado de worker.

#### Scenario: Usuário vê etapas de handoff
- **WHEN** ocorre transição interpret → Voice Design → TTS ou restart de worker TTS
- **THEN** há indicação de etapa/detalhe de handoff/lifecycle (não apenas silêncio até o próximo interpret/tts)
