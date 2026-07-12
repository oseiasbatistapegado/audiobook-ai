## MODIFIED Requirements

### Requirement: Load e reuso do modelo dentro do worker
Os pesos MUST ser assegurados via ModelManager no máximo uma vez por necessidade de download/validação de cache por execução de geração. Dentro de uma única invocação do worker Fish, o engine GPU MUST ser reutilizado para a sequência de SpeechChunks dessa invocação sem reload completo entre chunks, enquanto o headroom permanecer seguro segundo o `VRAMGuardian`. O orquestrador MAY encerrar o worker e iniciar outro (reload em processo fresco) por fim de fase (sem pending), degradação de VRAM sinalizada pelo guardian, falha controlada, ou teto opcional de residency quando habilitado. MUST NÃO exigir novo download de pesos só porque um worker encerrou. MUST NÃO forçar reload mid-fase apenas por contagem fixa de chunks quando o teto opcional estiver desabilitado.

#### Scenario: Múltiplos chunks sem reload no mesmo worker
- **WHEN** vários SpeechChunks são sintetizados na mesma invocação do worker com headroom seguro
- **THEN** a síntese completa sem novo download e sem novo load completo de pesos/engine entre esses chunks

#### Scenario: Novo worker após exit por guardian
- **WHEN** um worker Fish encerra por sinal do guardian (progressive ou headroom) e o orquestrador inicia outro com cache de pesos íntegro
- **THEN** o novo worker carrega o engine a partir do cache local sem reiniciar download completo

#### Scenario: Novo worker após exit
- **WHEN** um worker Fish encerra e o orquestrador inicia outro com cache de pesos íntegro
- **THEN** o novo worker carrega o engine a partir do cache local sem reiniciar download completo
