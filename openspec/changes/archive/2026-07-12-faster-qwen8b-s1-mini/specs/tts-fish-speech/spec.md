## ADDED Requirements

### Requirement: Pesos Fish seguem o alias selecionado
O backend Fish Speech in-process MUST carregar pesos obtidos via ModelManager para o alias `--fish-model` / default `s1-mini` (logical id correspondente). O contrato de síntese local sem HTTP e o isolamento em worker permanecem.

#### Scenario: Worker carrega path do alias ativo
- **WHEN** o worker Fish inicia com cache íntegro do alias selecionado (ex.: `s1-mini` ou `s2-pro`)
- **THEN** o engine é inicializado a partir do path desse alias sem baixar outro alias
