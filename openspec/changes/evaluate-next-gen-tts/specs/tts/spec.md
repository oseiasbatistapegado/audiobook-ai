## ADDED Requirements

### Requirement: Pesquisa TTS sem preferência inicial
A change `evaluate-next-gen-tts` SHALL tratar todos os candidatos (incluindo Fish Speech S1-mini, Fish Speech S2-pro, CosyVoice 3, Qwen3-TTS, IndexTTS2 e opcionais) com o mesmo protocolo de avaliação. Nenhum motor MUST receber preferência, peso ou atalho de aprovação por ser o baseline atual de produção.

#### Scenario: Protocolo idêntico
- **WHEN** dois candidatos distintos entram na mesma fase do funil
- **THEN** ambos usam o mesmo corpus, a mesma definição de RTF, o mesmo hardware oficial e os mesmos critérios de eliminação

### Requirement: Benchmarks no hardware oficial
Todos os resultados oficiais do spike MUST ser obtidos no hardware de referência do produto: AMD Ryzen 9 5950X, AMD Radeon RX 7900 XTX (24 GB), ROCm, Linux, Python 3.12. Resultados em CUDA ou NVIDIA MAY existir apenas como referência secundária e MUST NÃO substituir a decisão oficial.

#### Scenario: Número oficial
- **WHEN** um valor de RTF, VRAM ou estabilidade é citado no relatório final
- **THEN** esse valor foi medido no hardware oficial ROCm (ou o candidato foi eliminado na Fase 0 por inviabilidade nesse hardware)

### Requirement: Reprodutibilidade
Corpus de benchmark, scripts/comandos de medição, versões de modelo/pacote e resultados MUST ser documentados de forma que outro operador no mesmo hardware possa repetir as medições. O corpus oficial MUST ser versionado no repositório juntamente com os resultados.

#### Scenario: Corpus versionado
- **WHEN** a Fase 1 de qualidade inicia
- **THEN** existe um corpus oficial commitado (referências de speaker + textos + passagem longa) compartilhado por todos os candidatos restantes

### Requirement: Bloqueio de mudanças de produção até o relatório
Enquanto esta change de pesquisa não estiver concluída com relatório comparativo e recomendação arquitetural emitida, o projeto MUST NÃO alterar o pipeline de produção, a escolha de backend TTS/Voice Design, nem iniciar migração arquitetural motivada por esta pesquisa. Qualquer implementação de sucessor MUST ocorrer em change OpenSpec separada após a decisão documentada.

#### Scenario: Tentativa precoce de migração
- **WHEN** alguém propõe integrar um candidato ao hot path antes do relatório final
- **THEN** essa integração fica fora do escopo desta change e MUST NÃO ser mesclada como entrega desta pesquisa

### Requirement: Decisão arquitetural única baseada em evidência
Ao concluir o spike, MUST existir exatamente uma recomendação oficial entre: KEEP Fish Speech; REPLACE Fish Speech; REPLACE Voice Design; REPLACE toda a stack de voz. A recomendação MUST citar evidências do benchmark e MUST NÃO assumir vencedor a priori.

#### Scenario: Relatório emite decisão
- **WHEN** as fases aplicáveis do funil terminam e o relatório comparativo é publicado
- **THEN** o relatório declara uma única opção arquitetural com justificativa técnica ancorada nas medições
