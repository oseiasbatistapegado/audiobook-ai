## MODIFIED Requirements

### Requirement: Lease único de modelo GPU no orquestrador
O processo orquestrador do pipeline `generate` MUST NÃO carregar modelos GPU in-process de Voice Design ou da fase TTS. No máximo um worker GPU controlado pelo projeto MAY estar ativo por vez. O LifecycleManager SHALL conceder um lease exclusivo por fase GPU.

#### Scenario: Voice Design e TTS nunca simultâneos
- **WHEN** a fase Voice Design está em execução
- **THEN** nenhum worker TTS está ativo, e reciprocamente

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

### Requirement: Fish worker processa sequência limitada de chunks
O worker da fase TTS MUST carregar o modelo no máximo uma vez por invocação do worker e processar a sequência de SpeechChunks pendentes dessa invocação. MUST NÃO ser spawnado uma vez por SpeechChunk sob operação normal. O worker MUST permanecer residente e continuar sintetizando enquanto o `VRAMGuardian` considerar o headroom seguro. Hard reclaim mid-fase (EXIT com `controlled_restart_needed`) MUST ocorrer quando o guardian sinalizar degradação de free VRAM (crescimento progressivo pós-reclaim e/ou falha do gate `before_chunk` após reclaim). MUST NÃO encerrar só por contagem fixa de chunks quando o teto opcional de residency estiver desabilitado (default). A orquestração MUST expor esta fase via `run_tts_phase` / `run_tts_with_restarts` (não `run_fish_*`). O identificador arquitetural da fase MUST ser `tts`; o backend concreto MUST ser `qwen3-tts`.

#### Scenario: Múltiplos chunks no mesmo worker com headroom seguro
- **WHEN** há N>1 SpeechChunks pendentes e o guardian não sinaliza degradação de free VRAM
- **THEN** um único worker carrega o engine uma vez e sintetiza esses chunks em sequência sem EXIT por calendário

#### Scenario: Restart controlado sob degradação do guardian
- **WHEN** o worker detecta headroom insuficiente após reclaim ou crescimento progressivo de memória
- **THEN** o worker encerra de forma controlada sem sintetizar o próximo chunk inseguro, e o orquestrador MAY iniciar um worker fresco para continuar a partir do manifest

#### Scenario: Sem restart por calendário com teto desabilitado
- **WHEN** o teto opcional de residency está desabilitado e o guardian não sinaliza degradação após vários chunks
- **THEN** o worker NÃO emite `controlled_restart_needed` apenas porque atingiu um número fixo de chunks

#### Scenario: API de orquestração genérica
- **WHEN** o pipeline inicia a síntese de SpeechChunks
- **THEN** chama `run_tts_phase` / `run_tts_with_restarts` (nomes `run_fish_*` MUST NÃO permanecer como API de produto)

### Requirement: Budget de restart do Fish worker e por chunk
O orquestrador MUST permitir restarts controlados do worker TTS enquanto a geração fizer progresso útil, em vez de abortar por um teto global fixo de restarts por OOM. Restarts de reclaim planejado (`restart_reason` progressive, headroom ou residency) MUST NÃO contar como falha de progresso nem consumir tetos de OOM. Restarts por OOM inesperado / razões não planejadas MUST:

1. Continuar (spawn de worker fresco) enquanto chunks permanecerem pendentes e houver progresso (pelo menos um SpeechChunk novo `completed` desde o último restart cobrado zera o contador de stall).
2. Abortar quando ocorrerem `TTS_OOM_NO_PROGRESS_LIMIT` (default **3**) restarts cobrados **consecutivos** sem nenhum chunk novo completed.
3. Abortar quando o mesmo `SpeechChunk` id for alvo de `unexpected_oom` `TTS_CHUNK_MAX_OOM_ATTEMPTS` (default **3**) vezes na mesma fase de geração.

Um teto global absoluto (`TTS_WORKER_RESTART_BUDGET`) MAY existir como escape hatch; default MUST ser desabilitado (`0`). O mesmo `SpeechChunk` MUST ter no máximo **2** tentativas totais (primeira + 1 retry) para falhas hard (`FATAL` com `failed_chunk_id`); se falhar de novo, o pipeline MUST abortar com contexto diagnóstico. Unexpected OOM MUST NÃO queimar essas tentativas hard nem causar retries unbounded sem os gates de stall/por-chunk acima. Todos os limites MUST ser configuráveis. Quando `restart_reason=oom`, o `JobResult` MUST incluir `oom_chunk_id` identificando o chunk que disparou o OOM. Nomes de configuração `FISH_*` equivalentes MUST NÃO permanecer como interface de produto.

#### Scenario: OOM com progresso continua
- **WHEN** um worker encerra com `unexpected_oom` / `restart_reason=oom`, chunks pendentes restam, e após restarts anteriores a fase já completou pelo menos um chunk novo desde o último OOM
- **THEN** o orquestrador spawna um worker fresco e NÃO aborta só porque o número acumulado de OOMs na geração é alto

#### Scenario: Stall sem progresso aborta
- **WHEN** ocorrem N=`TTS_OOM_NO_PROGRESS_LIMIT` restarts cobrados consecutivos sem nenhum SpeechChunk novo completed
- **THEN** o pipeline falha com contexto de stall/OOM sem progresso em vez de spawnar indefinidamente

### Requirement: Teto opcional de residency como escape hatch
O sistema MAY expor um teto opcional de chunks por invocação do worker TTS (`TTS_CHUNKS_PER_WORKER` ou equivalente CLI/env). Default MUST ser **0** (desabilitado): reclaim mid-fase é guardian-driven. Valor >0 MAY forçar EXIT com `restart_reason=residency` após N chunks bem-sucedidos. Nomes `FISH_CHUNKS_PER_WORKER` MUST NÃO permanecer como interface de produto.

#### Scenario: Default sem teto de residency
- **WHEN** o teto opcional está desabilitado (default)
- **THEN** o worker TTS não reinicia só por contagem fixa de chunks

### Requirement: Transição entre modelos só com release verificado
Antes de spawnar Voice Design ou o worker TTS, o orquestrador MUST verificar que a VRAM liberada pela fase anterior satisfaz a política de release. O identificador arquitetural usado nos gates de load da fase TTS MUST ser `tts` (backend concreto `qwen3-tts` onde a configuração for específica do modelo).

#### Scenario: TTS só após release do Parler
- **WHEN** Voice Design conclui e a fase TTS vai iniciar
- **THEN** o orquestrador verifica release antes de spawnar o worker TTS

### Requirement: Ollama permanece fora do lease in-process
O LLM via Ollama (processo externo) MUST continuar a ser descarregado antes da fase TTS quando aplicável. Ollama NÃO conta como “modelo GPU in-process” do lease, mas o pipeline MUST evitar overlapping intencional de VRAM com workers GPU.

#### Scenario: Unload Ollama antes do TTS
- **WHEN** o pipeline vai spawnar o worker TTS após interpret remoto
- **THEN** Ollama foi unload antes do spawn/load do worker TTS
