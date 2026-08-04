## Purpose

Pipeline assíncrono com sobreposição entre LLM (interpret) e TTS (synthesis), permitindo que o LLM processe capítulo N+1 enquanto o TTS sintetiza capítulo N. Configuração via `TTS_ASYNC_OVERLAP`.

## Requirements

### Requirement: Thread producer para sobreposição LLM/TTS
O sistema SHALL executar a fase LLM (interpret) em uma thread producer enquanto a fase TTS executa na thread principal (consumer). A thread producer interpreta capítulo N+1 enquanto a thread principal sintetiza capítulo N. O overlap é configurável via `TTS_ASYNC_OVERLAP` (default 1).

#### Scenario: Overlap de 1 capítulo
- **WHEN** a thread principal sintetiza o capítulo 5
- **THEN** a thread producer está interpretando o capítulo 6

#### Scenario: Overlap configurável via env var
- **WHEN** `TTS_ASYNC_OVERLAP=0` é definido
- **THEN** o pipeline opera em modo linear (sem sobreposição)

#### Scenario: Overlap máximo de 3 capítulos
- **WHEN** `TTS_ASYNC_OVERLAP=5` é definido
- **THEN** o pipeline ajusta para 3 capítulos de overlap máximo

### Requirement: Queue assíncrona com tamanho limitado
A comunicação entre producer e consumer SHALL usar uma fila com tamanho máximo igual a `TTS_ASYNC_OVERLAP`. Quando a fila está cheia, o producer bloqueia até o consumer consumir. Isso limita o uso de memória.

#### Scenario: Producer bloqueia quando fila está cheia
- **WHEN** `TTS_ASYNC_OVERLAP=1` e a fila contém o capítulo N+1
- **THEN** a thread producer aguarda até o capítulo N ser consumido pelo consumer

#### Scenario: Consumer processa capítulo N enquanto producer faz N+1
- **WHEN** a fila contém apenas o capítulo N (cap N-1 já consumido)
- **THEN** o consumer processa o capítulo N e o producer enfileira o capítulo N+1

### Requirement: Coordenação entre fases LLM e TTS
O pipeline SHALL coordenar a transição entre fases:
1. LLM processa TODOS os capítulos primeiro (pré-processamento)
2. Async overlap inicia: TTS cap N enquanto LLM cap N+1
3. LLM termina, TTS completa os capítulos restantes

Isso garante que a interpretação esteja sempre 1 capítulo à frente da síntese.

#### Scenario: Fase LLM completa antes do async
- **WHEN** o pipeline entra no loop assíncrono
- **THEN** todos os capítulos já foram interpretados (pré-processamento completo)

#### Scenario: LLM termina antes do TTS
- **WHEN** todos os capítulos foram interpretados
- **THEN** o consumer continua processando capítulos restantes sem producer

#### Scenario: TTS termina antes do LLM (edge case)
- **WHEN** TTS é significativamente mais rápido que LLM (capítulos muito curtos)
- **THEN** o consumer aguarda o producer sem produzir garbage

### Requirement: Estado de resume para pipeline assíncrono
O manifest SHALL registrar o estado de BOTH LLM e TTS. Para resumir, o pipeline verifica:
- Capítulos interpretados mas não sintetizados: entra no async loop
- Capítulos nem interpretados nem sintetizados: LLM processa do início
- Capítulos já sintetizados: pula direto para async loop

#### Scenario: Resume após LLM completo mas TTS parcial
- **WHEN** 25/50 capítulos sintetizados, todos 50 interpretados
- **THEN** o pipeline retoma o async loop do capítulo 25 (sem re-interpretar)

#### Scenario: Resume após crash na fase LLM
- **WHEN** 30/50 capítulos interpretados, 0 sintetizados
- **THEN** o pipeline re-interpreta do capítulo 30 (ou retoma se parcial save existe)

### Requirement: Thread-safe manifest writes
Escritas no manifest SHALL ser thread-safe. O consumer thread (TTS) e producer thread (LLM) podem atualizar o manifest simultaneamente. Uso de atomic rename (`.tmp` → `rename`) + file lock por seção (tts/llm) é aceitável.

#### Scenario: Escrita simultânea não corrompe manifest
- **WHEN** consumer e producer atualizam o manifest simultaneamente
- **THEN** o manifest permanece válido e legível

#### Scenario: Crash durante escrita do manifest
- **WHEN** um worker crasha enquanto escreve `.tmp`
- **THEN** o arquivo `.tmp` é ignorado e o manifest anterior permanece válido

### Requirement: Graceful shutdown do async loop
Quando um worker TTS crasha ou o pipeline recebe um signal de shutdown:
1. Producer recebe signal de parada e encerra a thread LLM
2. Consumer finaliza o chunk atual e para
3. Manifest é flushado e fechado
4. Pipeline espera ambos os threads terminarem (timeout 30s)

#### Scenario: Shutdown após signal SIGINT
- **WHEN** o usuário pressiona Ctrl+C durante o async loop
- **THEN** o pipeline aguarda o chunk atual terminar e salva o estado

#### Scenario: Timeout de shutdown
- **WHEN** um thread não responde em 30s
- **THEN** o pipeline aborta o thread e salva o estado parcial

### Requirement: Transição entre modelos só com release verificado (modificado)
**De:** "Antes de spawnar Voice Design ou o worker TTS, o orquestrador MUST verificar que a VRAM liberada pela fase anterior satisfaz a política de release."
**Para:** "Além da verificação de release, o orquestrador calcula o headroom total necessário para N workers TTS (see `before_multi_worker_load_mib`). Se o headroom for insuficiente, o pipeline reduz o número de workers ou entra em modo single-worker."

#### Scenario: Redução automática de workers
- **WHEN** free VRAM < `before_multi_worker_load_mib` para 2 workers mas >= para 1 worker
- **THEN** o pipeline spawna 1 worker e loga "Reduced TTS workers: 2→1 (insufficient VRAM)"

### Requirement: Budget de restart do TTS worker (modificado)
**De:** Contagem global de restarts
**Para:** "Cada worker TTS individual conta seus próprios restarts. O orquestrador considera o pipeline saudável se pelo menos um worker estiver ativo e chunks pendentes existirem. Restart de worker individual não conta como stall global se outros workers estão ativos."

#### Scenario: Worker crashado não paralisa pipeline
- **WHEN** worker 1 crasha mas worker 0 continua ativo
- **THEN** o pipeline continua com worker 0 e spawna um worker 1' para substituir
