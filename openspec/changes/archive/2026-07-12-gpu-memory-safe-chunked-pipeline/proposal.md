## Why

O pipeline consegue carregar e executar modelos GPU individualmente, mas o consumo de VRAM durante a síntese Fish Speech não permanece estável: após um segmento bem-sucedido, a memória aproxima a capacidade total e o próximo allocation de attention causa OOM, podendo desestabilizar o compositor Wayland/Hyprland na RX 7900 XTX (24 GB ROCm). Spike local já mostrou que `release()` in-process do Fish Speech **não** devolve VRAM de forma fiável — apenas o encerramento do processo recupera memória. Estabilidade do desktop e síntese longa sem crescimento progressivo de VRAM são mais importantes que throughput máximo.

## What Changes

- Introduzir orquestração por fases com **no máximo um modelo GPU controlado pelo projeto residente por vez**.
- Tornar **process isolation** a estratégia oficial de hard reclaim entre modelos (Voice Design worker e Fish Speech worker); o processo principal NÃO carrega modelos GPU.
- Introduzir `SpeechChunk` como primitiva de pipeline (bounded workload TTS), com persistência imediata e manifest para **resume**.
- Introduzir `VRAMGuardian` com três thresholds distintos: `hard_floor_mib`, `before_chunk_target_mib`, `before_load_target_mib` (por backend).
- Exigir **unload verificado** entre fases de modelo: a transição só conclui quando a medição de VRAM confirma liberação (tipicamente após exit do worker).
- Reclaim entre chunks no worker Fish é best-effort; crescimento progressivo / risco ao hard floor → worker encerra de forma controlada e o orquestrador inicia worker fresco a partir do manifest.
- **BREAKING**: deixar de exigir (e de permitir como política) que o engine TTS permaneça carregado entre todos os segmentos quando isso conflitar com segurança de VRAM ou recuperação.
- **BREAKING**: a síntese Fish Speech deixa de ser “sempre in-process no processo da CLI”; passa a executar em worker isolado orquestrado pelo pipeline.
- LLM semantic chunking **fora de escopo** (change separado).
- Expor configuração centralizada de VRAM (defaults em config; CLI/env opcionais).

## Capabilities

### New Capabilities

- `gpu-lifecycle`: lease único de modelo GPU, lifecycle `load → execute → unload/exit`, workers isolados para Voice Design e Fish Speech, verificação de liberação de VRAM entre fases.
- `vram-guardian`: snapshots de VRAM (system free vs PyTorch allocated/reserved), três thresholds, decisões `can_start_work` / `require_safe_headroom`, telemetria estruturada, falha segura sem usar OOM como controle.
- `speech-chunking`: primitiva `SpeechChunk` (id estável, sequência, workload limitado, metadata para resume), limites configuráveis, boundaries preferenciais (parágrafo → turno → sentença → split).
- `chunk-resume`: manifest ordenado, persistência imediata de áudio por chunk, skip de chunks válidos já concluídos após crash/OOM controlado/restart de worker.

### Modified Capabilities

- `vram-handoff`: supersede a exigência de manter o engine TTS entre todos os segmentos do capítulo; handoff passa a ser por fases (interpret → voice-design worker → fish worker → merge) com hard reclaim verificado.
- `tts-fish-speech`: síntese via worker isolado (não proibir subprocess para isolamento de GPU); engine reutilizado **dentro** do worker para uma sequência limitada de SpeechChunks; reclaim/monitoramento entre chunks; unload real = exit do worker.
- `generative-voice-design`: fase Voice Design executa em worker isolado; exit do worker é o hard reclaim antes do Fish Speech.
- `generate-cli`: progresso/telemetria de workers, chunks e resume; opções/env para thresholds de VRAM e limites de chunk TTS.

## Impact

- Código: `pipeline.py`, `tts/fish_speech.py`, `voice/generator.py`, `state/voices.py`, `config.py`, `cli.py`, `utils/workdir.py`; novos módulos sob `gpu/` (guardian/lifecycle) e chunking/manifest.
- Specs principais: `vram-handoff`, `tts-fish-speech`, `generative-voice-design`, `generate-cli`; novas capabilities acima.
- Hardware alvo: AMD RX 7900 XTX 24 GB / ROCm / Hyprland — estabilidade do compositor é critério de aceite.
- Testes: unitários com fake memory/providers e fake workers; integração de ordem de lifecycle; smoke real multi-chunk na 7900 XTX.
- Não-objetivos: semantic chunking LLM; throughput máximo; multi-GPU; paralelismo de modelos; qualidade pt-BR do Voice Design; substituir Fish Speech ou Parler.
