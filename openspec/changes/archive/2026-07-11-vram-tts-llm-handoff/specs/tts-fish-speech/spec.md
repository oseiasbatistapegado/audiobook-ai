## ADDED Requirements

### Requirement: Liberação explícita do engine GPU
`FishSpeechBackend` SHALL expor um método de liberação (ex.: `release`) que descarta o engine in-process da memória/GPU, marca o backend como não carregado e tenta devolver VRAM ao sistema (incluindo limpeza de cache CUDA/ROCm quando aplicável). Pesos em disco via ModelManager MUST permanecer intactos. A interface `TTSBackend` SHALL permitir essa liberação (implementação no-op aceitável em backends que não usam GPU).

#### Scenario: Release deixa synthesize a precisar de reload
- **WHEN** `release` é chamado após o engine ter sido carregado
- **THEN** uma chamada posterior a `synthesize` (ou `ensure_ready` de load) recarrega o engine a partir do path já assegurado pelo ModelManager sem novo download completo se o cache estiver íntegro

#### Scenario: Release é idempotente
- **WHEN** `release` é chamado com o engine já ausente
- **THEN** a operação completa sem erro

## MODIFIED Requirements

### Requirement: Load único e reuso do modelo
O backend MUST assegurar os pesos via ModelManager no máximo uma vez por necessidade de download/validação de cache por execução de geração. O engine GPU MUST ser reutilizado para todos os `synthesize` consecutivos sem `release` no meio. Após um `release` intencional (handoff de VRAM), o backend MAY recarregar o engine na próxima síntese ou `ensure_ready` de load. MUST NÃO exigir novo download de pesos só porque o engine foi liberado da GPU.

#### Scenario: Múltiplos segmentos sem reload
- **WHEN** vários `synthesize` são chamados na mesma instância do backend após o init e sem `release` entre eles
- **THEN** a síntese completa sem novo download e sem novo load completo de pesos/engine entre as chamadas

#### Scenario: Reload após release intencional
- **WHEN** o pipeline chama `release` e depois solicita síntese novamente com cache de pesos íntegro
- **THEN** o backend recarrega o engine a partir do cache local e sintetiza sem reiniciar download completo
