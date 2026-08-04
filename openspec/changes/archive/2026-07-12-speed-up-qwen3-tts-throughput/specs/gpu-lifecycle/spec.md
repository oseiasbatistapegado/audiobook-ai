## MODIFIED Requirements

### Requirement: TTS worker processa sequência limitada de chunks
O worker da fase TTS MUST carregar o modelo no máximo uma vez por invocação do worker e processar a sequência de SpeechChunks pendentes dessa invocação. MUST NÃO ser spawnado uma vez por SpeechChunk sob operação normal. O worker MUST permanecer residente e continuar sintetizando enquanto o `VRAMGuardian` considerar o headroom seguro sob a política de **pressão real** (não falsos positivos de free-drop). Hard reclaim mid-fase (EXIT com `controlled_restart_needed`) MUST ocorrer quando o guardian sinalizar pressão real, falha do gate `before_chunk` após reclaim, OOM, ou teto opcional de residency. MUST NÃO encerrar só por contagem fixa de chunks quando o teto opcional de residency estiver desabilitado (default). A orquestração MUST expor esta fase via `run_tts_phase` / `run_tts_with_restarts`. O identificador arquitetural da fase MUST ser `tts`; o backend concreto MUST ser `qwen3-tts`.

#### Scenario: Múltiplos chunks no mesmo worker com headroom seguro
- **WHEN** há N>1 SpeechChunks pendentes e o guardian não sinaliza pressão real de memória
- **THEN** um único worker carrega o engine uma vez e sintetiza esses chunks em sequência sem EXIT por calendário

#### Scenario: Restart controlado sob pressão real
- **WHEN** o worker detecta headroom insuficiente após reclaim ou crescimento real de allocated/reserved / free próximo ao hard floor
- **THEN** o worker encerra de forma controlada sem sintetizar o próximo chunk inseguro, e o orquestrador MAY iniciar um worker fresco para continuar a partir do manifest

#### Scenario: Sem restart por calendário com teto desabilitado
- **WHEN** o teto opcional de residency está desabilitado e o guardian não sinaliza pressão real após vários chunks
- **THEN** o worker NÃO emite `controlled_restart_needed` apenas porque atingiu um número fixo de chunks

#### Scenario: API de orquestração genérica
- **WHEN** o pipeline inicia a síntese de SpeechChunks
- **THEN** chama `run_tts_phase` / `run_tts_with_restarts` (nomes `run_fish_*` MUST NÃO permanecer como API de produto)

## ADDED Requirements

### Requirement: Residência TTS na fase contínua
Enquanto houver SpeechChunks TTS pendentes na fase TTS contínua do `generate`, o orquestrador MUST preferir manter o worker/modelo Qwen3-TTS residente em vez de unload/reload entre capítulos. Unload MUST ocorrer ao fim da fase TTS, em controlled restart real, ou quando a próxima fase exigir outro backend GPU (ex.: interpret) e a exclusão mútua exigir.

#### Scenario: Capítulos consecutivos sem reload desnecessário
- **WHEN** a fase TTS contínua tem chunks pendentes de múltiplos capítulos e o guardian não exige reclaim
- **THEN** o modelo Qwen3-TTS não é descarregado entre esses capítulos só por fronteira de capítulo
