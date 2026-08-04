## MODIFIED Requirements

### Requirement: Load e reuso do modelo dentro do worker TTS
Os pesos MUST ser assegurados via ModelManager no máximo uma vez por necessidade de download/validação por execução. Dentro de uma invocação do worker TTS, o engine GPU MUST ser reutilizado para a sequência de SpeechChunks enquanto o headroom permanecer seguro segundo o `VRAMGuardian` (pressão real). O orquestrador MUST preferir uma fase TTS contínua com worker residente; MAY encerrar o worker e iniciar outro por fim de fase, pressão real de VRAM, falha controlada, ou teto opcional de residency. MUST NÃO exigir novo download só porque um worker encerrou.

#### Scenario: Múltiplos chunks sem reload no mesmo worker
- **WHEN** vários SpeechChunks são sintetizados na mesma invocação do worker com headroom seguro
- **THEN** a síntese completa sem novo download e sem novo load completo entre esses chunks

## ADDED Requirements

### Requirement: Cache de VoiceClonePrompt por voice_id
Quando a API Qwen3-TTS expuser preparação de prompt de clone (`create_voice_clone_prompt` ou equivalente), o worker/backend MUST construir o prompt uma vez por `voice_id` a partir de `reference.wav` + `reference.txt`, cachear no processo, e reutilizar nos chunks subsequentes da mesma voz. O cache MUST ser descartado no `release()` / exit do worker. MUST NÃO reprocessar a mesma referência em cada chunk quando o cache hit for possível.

#### Scenario: Segunda síntese da mesma voz reutiliza prompt
- **WHEN** dois SpeechChunks consecutivos usam o mesmo `voice_id` com API de prompt disponível
- **THEN** `create_voice_clone_prompt` (ou equivalente) não é reexecutado para o segundo chunk

#### Scenario: Cache morre com o worker
- **WHEN** o worker TTS encerra
- **THEN** o cache de VoiceClonePrompt não sobrevive em outro processo

### Requirement: Batching e overlap oficiais quando disponíveis
O worker MUST usar batching/multi-request suportado pela API oficial do Qwen3-TTS quando disponível, priorizando uma instância do modelo. MUST NÃO carregar múltiplas cópias do modelo por padrão. Preparação CPU do próximo request MAY sobrepor a geração GPU atual desde que ordem determinística, resume, e persist-before-reclaim sejam preservados.

#### Scenario: Sem multi-instância por padrão
- **WHEN** a VRAM livre permitiria múltiplas cópias do Qwen3-TTS
- **THEN** o produto não spawna múltiplas instâncias só por folga de VRAM

#### Scenario: Persist-before-reclaim com overlap
- **WHEN** overlap CPU/GPU está ativo
- **THEN** o áudio do chunk N está persistido e o manifest atualizado antes do reclaim e antes de considerar N concluído
