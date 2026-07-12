# Contrato da pesquisa — Next-Generation TTS

Este documento fixa as regras da change `evaluate-next-gen-tts`. Os requisitos normativos espelham `spec.md` nesta mesma pasta.

## Neutralidade

Nenhum motor possui preferência inicial. Fish Speech (S1-mini / S2-pro), CosyVoice 3, Qwen3-TTS, IndexTTS2 e demais candidatos passam pelo **mesmo** protocolo (corpus, RTF, pt-BR, VRAM, funil de fases).

## Reprodutibilidade

- Corpus oficial versionado no repositório, junto com resultados.
- Versões de pacotes/modelos e comandos de medição documentados.
- Outro operador no hardware oficial deve conseguir repetir os números.

## Hardware oficial

Benchmarks decisórios **somente** em:

- AMD Ryzen 9 5950X
- AMD Radeon RX 7900 XTX (24 GB)
- ROCm / Linux / Python 3.12

CUDA/NVIDIA = referência secundária apenas.

## Bloqueio de produção

Mudanças na arquitetura de produção (pipeline, backend TTS, Voice Design, migração) **só** poderão ocorrer **após**:

1. conclusão do benchmark;
2. emissão do relatório comparativo;
3. recomendação arquitetural única documentada.

Esta change **não** implementa substitutos no hot path.

## Decisão permitida (uma)

- KEEP Fish Speech
- REPLACE Fish Speech
- REPLACE Voice Design
- REPLACE toda a stack de voz

A escolha MUST basear-se exclusivamente nas evidências do spike.
