## Why

O hot path de voz (Parler-TTS para Voice Design + Fish Speech para síntese longa) é o gargalo do produto na RX 7900 XTX / ROCm: RTF alto (s2-pro ~13×), pressão e fragmentação de VRAM, restarts frequentes de worker e estimativa de vários dias para um volume longo. Antes de qualquer migração, o projeto precisa de evidência empírica comparável — não de preferência tecnológica — sobre qual stack de voz oferece o melhor equilíbrio entre qualidade pt-BR, clonagem, throughput, estabilidade e integração.

## What Changes

- **Research-only:** protocolo de spike comparativo entre motores TTS (e, quando aplicável, Voice Design), com corpus versionado, avaliação cega, benchmarks reproduzíveis no hardware oficial e relatório com recomendação arquitetural única.
- **Nova capability** `tts` (contrato da pesquisa): neutralidade entre candidatos, hardware de referência, reprodutibilidade e bloqueio explícito de mudanças de produção até o relatório final.
- Corpus oficial de benchmark (referências de speaker + frases + passagem ~10 min) versionado no repositório junto com resultados.
- Checklist de avaliação cega (2 avaliadores, amostras sem identificação do motor).
- Entregáveis: fichas por candidato, tabela consolidada, logs de estabilidade, decisão entre KEEP Fish / REPLACE Fish / REPLACE Voice Design / REPLACE toda a stack.

**Cláusula de pesquisa (obrigatória):** esta change é exclusivamente de pesquisa. Nenhuma alteração no pipeline de produção, escolha de backend ou migração arquitetural deverá ser implementada antes da conclusão do benchmark e da emissão do relatório final.

## Capabilities

### New Capabilities

- `tts`: contrato da pesquisa de avaliação next-gen TTS — neutralidade, corpus/benchmarks reproduzíveis no hardware oficial (RX 7900 XTX / ROCm), critérios de eliminação, e proibição de alterar a arquitetura de produção até a decisão documentada.

### Modified Capabilities

- (nenhuma) — esta change não altera requisitos de produção de `tts-fish-speech`, `generative-voice-design`, `vram-guardian`, nem demais capabilities existentes.

## Impact

- **Código de produção:** nenhum (orquestração, workers Fish/Parler, factory TTS, CLI).
- **Repositório:** artefatos sob `openspec/changes/evaluate-next-gen-tts/`; corpus e resultados de benchmark versionados (paths definidos no design).
- **Runtime do spike:** downloads/instalações **isoladas** de candidatos (Fish S1-mini / S2-pro, CosyVoice 3, Qwen3-TTS, IndexTTS2; opcionais XTTS v2, F5-TTS, Kokoro) apenas para medição — sem registrar novos backends no produto.
- **Hardware:** todos os números oficiais no Ryzen 9 5950X + RX 7900 XTX 24 GB / ROCm / Linux / Python 3.12; CUDA/NVIDIA só como referência secundária.
- **Decisão futura:** uma change de *implementation* separada poderá ser aberta **somente** após o relatório e a recomendação oficial desta pesquisa.
