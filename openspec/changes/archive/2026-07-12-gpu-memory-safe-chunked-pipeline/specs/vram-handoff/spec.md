## MODIFIED Requirements

### Requirement: Exclusão mútua de VRAM entre LLM e TTS
O pipeline `generate` SHALL garantir que nenhum worker/engine Fish Speech esteja residente na GPU durante a fase `interpret` (Ollama) e que o modelo Ollama não esteja residente na memória/VRAM do host durante a fase TTS, quando ambos os backends estiverem em uso. Voice Design e Fish Speech MUST NÃO estar ativos simultaneamente.

#### Scenario: Interpret com TTS liberado
- **WHEN** o pipeline inicia a interpretação de um capítulo
- **THEN** nenhum worker Fish Speech está ativo (e o orquestrador não mantém engine TTS carregado)

#### Scenario: TTS com Ollama liberado
- **WHEN** o pipeline inicia a fase Fish Speech após o interpret
- **THEN** o modelo Ollama foi descarregado (`unload`) antes do spawn/load do worker TTS

### Requirement: Transições de handoff por fases GPU
O pipeline MUST orquestrar fases com hard reclaim verificado entre modelos GPU: liberar qualquer worker TTS → interpretar → descarregar Ollama → Voice Design worker (se necessário) → verificar release → Fish Speech worker (SpeechChunks) → verificar release → merge. Manter o engine TTS carregado entre todos os segmentos/chunks MUST NÃO ser exigido quando conflitar com segurança de VRAM, monitoramento de headroom, ou restart controlado de worker.

#### Scenario: Sequência de fases com workers
- **WHEN** um livro requer Voice Design e síntese Fish Speech
- **THEN** o Voice Design worker termina e a liberação de VRAM é verificada antes do Fish Speech worker iniciar

#### Scenario: Restart de worker entre chunks
- **WHEN** o worker Fish encerra de forma controlada com SpeechChunks ainda pendentes
- **THEN** o orquestrador MAY iniciar um novo worker para continuar sem violar o lease único e sem exigir que o engine anterior permaneça residente

#### Scenario: Capítulos/fases subsequentes liberam VRAM para o LLM
- **WHEN** a fase TTS termina e uma nova interpretação remota é necessária
- **THEN** nenhum worker Fish está ativo antes do interpret

### Requirement: Progresso visível do handoff
O pipeline SHALL notificar progresso (callback / Rich) e registrar log quando executar unload de Ollama, spawn/exit de workers GPU, verificação de release de VRAM, ou restart controlado de worker.

#### Scenario: Usuário vê etapas de handoff
- **WHEN** ocorre transição interpret → Voice Design → Fish ou restart de worker TTS
- **THEN** há indicação de etapa/detalhe de handoff/lifecycle (não apenas silêncio até o próximo interpret/tts)
