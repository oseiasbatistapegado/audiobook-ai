## Purpose

Orquestração de workers GPU isolados com lease exclusivo, hard reclaim via exit do processo, e IPC por job directory versionado.

## Requirements

### Requirement: Lease único de modelo GPU no orquestrador
O processo orquestrador do pipeline `generate` MUST NÃO carregar modelos GPU in-process de Voice Design ou da fase TTS. No máximo um worker GPU por fase/backend está ativo, exceto para TTS onde N workers paralelos MAY estar ativos simultaneamente sob controle do `TTS_MULTI_WORKER_COUNT`. O LifecycleManager SHALL conceder um lease exclusivo por fase GPU (exceto TTS multi-worker).

#### Scenario: Voice Design e TTS nunca simultâneos
- **WHEN** a fase Voice Design está em execução
- **THEN** nenhum worker TTS está ativo, e reciprocamente

#### Scenario: N workers TTS simultâneos
- **WHEN** `TTS_MULTI_WORKER_COUNT=2`
- **THEN** 2 workers TTS estão ativos simultaneamente, ambos com lease do LifecycleManager

#### Scenario: Orquestrador sem engine residente
- **WHEN** o orquestrador conclui uma fase GPU (worker exit)
- **THEN** o processo orquestrador não mantém referências a engines/modelos GPU carregados dessa fase

### Requirement: Workers isolados como hard reclaim oficial
Voice Design e a fase TTS MUST executar em processos worker isolados. O encerramento (exit) do worker SHALL ser o mecanismo oficial de hard reclaim de VRAM entre fases de modelo. Unload apenas in-process MUST NÃO ser tratado como prova suficiente de liberação no hot path do produto sob ROCm.

#### Scenario: Exit do Voice Design libera lease
- **WHEN** o worker de Voice Design termina e o LifecycleManager verifica a liberação
- **THEN** a fase é considerada concluída somente se a VRAM medida satisfizer a política de release verificada

#### Scenario: Exit do worker TTS libera lease
- **WHEN** o worker TTS termina (sucesso ou saída controlada)
- **THEN** o orquestrador verifica liberação de VRAM antes de iniciar outra fase GPU ou declarar a fase TTS concluída

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

### Requirement: Residência TTS na fase contínua
Enquanto houver SpeechChunks TTS pendentes na fase TTS contínua do `generate`, o orquestrador MUST preferir manter o worker/modelo Qwen3-TTS residente em vez de unload/reload entre capítulos. Unload MUST ocorrer ao fim da fase TTS, em controlled restart real, ou quando a próxima fase exigir outro backend GPU (ex.: interpret) e a exclusão mútua exigir.

#### Scenario: Capítulos consecutivos sem reload desnecessário
- **WHEN** a fase TTS contínua tem chunks pendentes de múltiplos capítulos e o guardian não exige reclaim
- **THEN** o modelo Qwen3-TTS não é descarregado entre esses capítulos só por fronteira de capítulo

### Requirement: Budget de restart do TTS worker e por chunk
O orquestrador MUST permitir restarts controlados do worker TTS enquanto a geração fizer progresso útil, em vez de abortar por um teto global fixo de restarts por OOM. Restarts de reclaim planejado (`restart_reason` progressive, headroom ou residency) MUST NÃO contar como falha de progresso nem consumir tetos de OOM. Restarts por OOM inesperado / razões não planejadas MUST:

1. Continuar (spawn de worker fresco) enquanto chunks permanecerem pendentes e houver progresso (pelo menos um SpeechChunk novo `completed` desde o último restart cobrado zera o contador de stall).
2. Abortar quando ocorrerem `TTS_OOM_NO_PROGRESS_LIMIT` (default **3**) restarts cobrados **consecutivos** sem nenhum chunk novo completed.
3. Abortar quando o mesmo `SpeechChunk` id for alvo de `unexpected_oom` `TTS_CHUNK_MAX_OOM_ATTEMPTS` (default **3**) vezes na mesma fase de geração.

Um teto global absoluto (`TTS_WORKER_RESTART_BUDGET`) MAY existir como escape hatch; default MUST ser desabilitado (`0`). O mesmo `SpeechChunk` MUST ter no máximo **2** tentativas totais (primeira + 1 retry) para falhas hard (`FATAL` com `failed_chunk_id`); se falhar de novo, o pipeline MUST abortar com contexto diagnóstico. Unexpected OOM MUST NÃO queimar essas tentativas hard nem causar retries unbounded sem os gates de stall/por-chunk acima. Todos os limites MUST ser configuráveis. Quando `restart_reason=oom`, o `JobResult` MUST incluir `oom_chunk_id` identificando o chunk que disparou o OOM. Nomes de configuração `FISH_*` equivalentes MUST NÃO permanecer como interface de produto.

Em modo multi-worker, cada worker TTS individual conta seus próprios restarts. O orquestrador considera o pipeline saudável se pelo menos um worker estiver ativo e chunks pendentes existirem. Restart de worker individual não conta como stall global se outros workers estão ativos.

#### Scenario: OOM com progresso continua
- **WHEN** um worker encerra com `unexpected_oom` / `restart_reason=oom`, chunks pendentes restam, e após restarts anteriores a fase já completou pelo menos um chunk novo desde o último OOM
- **THEN** o orquestrador spawna um worker fresco e NÃO aborta só porque o número acumulado de OOMs na geração é alto

#### Scenario: Stall sem progresso aborta
- **WHEN** ocorrem N=`TTS_OOM_NO_PROGRESS_LIMIT` restarts cobrados consecutivos sem nenhum SpeechChunk novo completed
- **THEN** o pipeline falha com contexto de stall/OOM sem progresso em vez de spawnar indefinidamente

#### Scenario: Mesmo chunk OOM demais aborta
- **WHEN** o mesmo `oom_chunk_id` atinge `TTS_CHUNK_MAX_OOM_ATTEMPTS` OOMs na fase
- **THEN** o pipeline falha com diagnóstico desse chunk id e NÃO continua reiniciando só por esse id

#### Scenario: Restart progressive não conta como stall
- **WHEN** o worker encerra com `controlled_restart_needed` e `restart_reason=progressive` com chunks pendentes
- **THEN** o orquestrador spawna um worker fresco sem incrementar contadores de OOM/stall

#### Scenario: Restart headroom não conta como stall
- **WHEN** o worker encerra com `controlled_restart_needed` e `restart_reason=headroom` com chunks pendentes
- **THEN** o orquestrador spawna um worker fresco sem incrementar contadores de OOM/stall

#### Scenario: Segunda falha hard no mesmo chunk aborta
- **WHEN** o mesmo SpeechChunk id falha duas vezes com falha hard (`FATAL`)
- **THEN** o pipeline falha com diagnóstico do chunk e NÃO continua reiniciando workers só por esse id

#### Scenario: Teto global desabilitado por default
- **WHEN** `TTS_WORKER_RESTART_BUDGET` está desabilitado (default)
- **THEN** o orquestrador NÃO aborta por esgotamento de budget global de restarts

### Requirement: Teto opcional de residency como escape hatch
O sistema MAY expor um teto opcional de chunks por invocação do worker TTS (`TTS_CHUNKS_PER_WORKER` ou equivalente CLI/env). Default MUST ser **0** (desabilitado): reclaim mid-fase é guardian-driven. Valor >0 MAY forçar EXIT com `restart_reason=residency` após N chunks bem-sucedidos. Nomes `FISH_CHUNKS_PER_WORKER` MUST NÃO permanecer como interface de produto.

#### Scenario: Default sem teto de residency
- **WHEN** o teto opcional está desabilitado (default)
- **THEN** o worker TTS não reinicia só por contagem fixa de chunks

#### Scenario: Teto habilitado força reclaim
- **WHEN** o teto está configurado para N>0 e o worker completa N chunks com mais pendentes
- **THEN** o worker emite `controlled_restart_needed` com `restart_reason=residency`

### Requirement: Job directory versionado como IPC canônico
A comunicação autoritativa orquestrador↔worker MUST usar um job directory sob o work-dir book-scoped. O worker recebe o path do job; progresso durável passa por arquivos/manifest. stdout/stderr MAY carregar logs, mas MUST NÃO ser o canal autoritativo de estado. Arquivos de job MUST ser versionados e escritos atomicamente.

#### Scenario: Progresso sobrevive ao crash do worker
- **WHEN** um worker TTS crasha após persistir um chunk e atualizar o manifest
- **THEN** o orquestrador consegue retomar a partir dos arquivos do job/manifest sem depender do stdout do processo morto

### Requirement: Transição entre modelos só com release verificado
Além da verificação de release, o orquestrador calcula o headroom total necessário para N workers TTS (see `before_multi_worker_load_mib`). Se o headroom for insuficiente, o pipeline reduz o número de workers ou entra em modo single-worker. Antes de spawnar Voice Design ou o worker TTS, o orquestrador MUST verificar que a VRAM liberada pela fase anterior satisfaz a política de release. O identificador arquitetural usado nos gates de load da fase TTS MUST ser `tts` (backend concreto `qwen3-tts` onde a configuração for específica do modelo).

#### Scenario: Redução automática de workers
- **WHEN** free VRAM < `before_multi_worker_load_mib` para 2 workers mas >= para 1 worker
- **THEN** o pipeline spawna 1 worker e loga "Reduced TTS workers: 2→1 (insufficient VRAM)"

#### Scenario: TTS só após release do Parler
- **WHEN** Voice Design conclui e a fase TTS vai iniciar
- **THEN** o orquestrador verifica release antes de spawnar o worker TTS

#### Scenario: Falha segura se VRAM não liberou
- **WHEN** o worker anterior saiu mas free VRAM permanece abaixo do target de load do próximo backend
- **THEN** o pipeline falha com erro contextual distinguindo “memória não liberada” e NÃO spawna o próximo worker GPU

### Requirement: Ollama permanece fora do lease in-process
O LLM via Ollama (processo externo) MUST continuar a ser descarregado antes da fase TTS quando aplicável. Ollama NÃO conta como “modelo GPU in-process” do lease, mas o pipeline MUST evitar overlapping intencional de VRAM com workers GPU.

#### Scenario: Unload Ollama antes do TTS
- **WHEN** o pipeline vai spawnar o worker TTS após interpret remoto
- **THEN** Ollama foi unload antes do spawn/load do worker TTS
