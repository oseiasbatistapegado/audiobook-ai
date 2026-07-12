## MODIFIED Requirements

### Requirement: Fase dedicada e unload do modelo de design
O modelo de Voice Design MUST rodar em fase dedicada (worker isolado) para vozes faltantes do livro e MUST NÃO ser invocado por cada segmento/chunk de diálogo. Após gerar as refs faltantes, o worker MUST encerrar; o orquestrador MUST verificar liberação de VRAM antes de carregar/spawnar o Fish Speech. Unload apenas in-process MAY existir dentro do worker, mas o hard reclaim oficial entre Voice Design e Fish Speech É o exit do worker.

#### Scenario: Batch antes do TTS com worker
- **WHEN** o pipeline identifica N personagens sem voz no `book_id` atual
- **THEN** spawna o worker de Voice Design, gera as N refs, persiste, encerra o worker, verifica release de VRAM, e só então spawna o Fish Speech worker para síntese

#### Scenario: Sem Parler residente durante Fish
- **WHEN** o Fish Speech worker está ativo
- **THEN** o modelo de Voice Design não está carregado em nenhum processo controlado pelo projeto
