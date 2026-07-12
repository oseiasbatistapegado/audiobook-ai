## ADDED Requirements

### Requirement: Exclusão mútua de VRAM entre LLM e TTS
O pipeline `generate` SHALL garantir que o engine Fish Speech não esteja residente na GPU durante a fase `interpret` (Ollama) e que o modelo Ollama não esteja residente na memória/VRAM do host durante a fase TTS do mesmo capítulo, quando ambos os backends estiverem em uso.

#### Scenario: Interpret com TTS liberado
- **WHEN** o pipeline inicia a interpretação de um capítulo com `FishSpeechBackend` e `OllamaBackend`
- **THEN** o engine TTS foi liberado (`release`) antes da chamada LLM (ou nunca foi carregado ainda nesta execução)

#### Scenario: TTS com Ollama liberado
- **WHEN** o pipeline inicia a síntese do primeiro segmento de um capítulo após o interpret
- **THEN** o modelo Ollama foi descarregado (`unload`) antes do load/reload do engine TTS

### Requirement: Transições de handoff por capítulo
Para cada capítulo, o pipeline MUST executar a sequência: liberar TTS → interpretar → descarregar Ollama → carregar TTS → sintetizar todos os segmentos do capítulo → liberar TTS (preparando o próximo capítulo). MUST NÃO liberar/recarregar o engine TTS entre segmentos consecutivos do mesmo capítulo.

#### Scenario: Múltiplos segmentos sem reload intermediário
- **WHEN** um capítulo produz N>1 diálogos e o engine TTS já está carregado após o unload do Ollama
- **THEN** os N `synthesize` reutilizam o mesmo engine sem novo load completo entre eles

#### Scenario: Capítulos subsequentes liberam VRAM para o LLM
- **WHEN** o capítulo N termina a síntese e o capítulo N+1 inicia o interpret
- **THEN** o engine TTS foi liberado entre as duas fases

### Requirement: Progresso visível do handoff
O pipeline SHALL notificar progresso (callback / Rich) e registrar log quando executar release de TTS, unload de Ollama ou load/reload de TTS por causa do handoff de VRAM.

#### Scenario: Usuário vê etapas de handoff
- **WHEN** ocorre uma transição LLM→TTS ou TTS→LLM com backends reais
- **THEN** há indicação de etapa/detalhe de handoff (não apenas silêncio até o próximo interpret/tts)
