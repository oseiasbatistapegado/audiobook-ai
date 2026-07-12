## MODIFIED Requirements

### Requirement: Síntese com voz padrão empacotada
Além da interface in-process existente, o `FishSpeechBackend` MUST sintetizar usando a referência pt-BR persistida do personagem/narrator (registry do `book_id` ou override). Fish Speech MUST NÃO criar a identidade vocal. A ausência de `./references/` do usuário MUST NÃO ser erro quando o registry do livro tem ref pt-BR válida. MUST NÃO usar fallback silencioso para voz de outro idioma, stock bank, ou voz de outro personagem.

#### Scenario: MVP smoke com refs geradas
- **WHEN** o pipeline solicita TTS com `voice_id` materializado no registry do livro (pt-BR) e pesos carregados
- **THEN** `FishSpeechBackend.synthesize` retorna `AudioSegment` não vazio sem setup manual de vozes

#### Scenario: voice_id com registry pt-BR
- **WHEN** o `voice_map` referencia um `voice_id` materializado com `language=pt-BR`
- **THEN** o backend sintetiza usando essa referência (não substitui por narrator sem necessidade)

#### Scenario: voice_id sem referência pt-BR válida
- **WHEN** o `voice_map` referencia um `voice_id` sem pasta resolvível pt-BR
- **THEN** o backend falha com erro contextual (sem clonar inglês ou stock silenciosamente)

## ADDED Requirements

### Requirement: Consumo de vozes do registry sem regenerar por frase
O backend TTS MUST tratar `voice_id` como identidade já materializada pelo Voice Design: MUST NÃO invocar Voice Design / `generate_voice` a cada `synthesize`.

#### Scenario: Múltiplos synthesize reutilizam a mesma ref
- **WHEN** vários `synthesize` são chamados com o mesmo `voice_id` válido na mesma geração
- **THEN** cada chamada usa a mesma pasta de referência já resolvida sem regenerar identidade

### Requirement: Preservar distinção entre speakers gerados
Quando duas referências geradas são perceptualmente distintas, a clonagem Fish Speech MUST preservar distinção perceptível entre os speakers nas saídas sintetizadas para o mesmo texto de teste (critério de aceite do spike/smoke).

#### Scenario: Carlos e João permanecem distintos após clone
- **WHEN** Fish Speech sintetiza a mesma frase com as refs de dois personagens gerados distintos
- **THEN** as saídas permanecem perceptualmente atribuíveis a speakers diferentes
