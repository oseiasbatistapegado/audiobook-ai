## Purpose

Interface `TTSBackend` com implementação Qwen3-TTS local (worker isolado sob LifecycleManager) para síntese Voice Clone a partir de referências Parler.

## Requirements

### Requirement: Interface TTSBackend com único backend Qwen3-TTS
O sistema SHALL expor a interface `TTSBackend` com `synthesize(TTSRequest) -> AudioSegment`. O factory MUST resolver somente o backend `qwen3-tts` (alias opcional `qwen3tts`). MUST NÃO registrar ou aceitar `fish`, `fish-speech`, `s1-mini`, `s2-pro`, `cosyvoice` ou `cosyvoice3` como backends suportados.

#### Scenario: Factory resolve qwen3-tts
- **WHEN** a configuração/pipeline solicita o backend `qwen3-tts` (ou alias `qwen3tts`)
- **THEN** o factory retorna uma instância de `Qwen3TTSBackend` que implementa `TTSBackend`

#### Scenario: Backend Fish rejeitado
- **WHEN** a configuração solicita `fish-speech` ou alias Fish legado
- **THEN** o factory falha com erro claro indicando que apenas `qwen3-tts` é suportado

### Requirement: Inferência Qwen3-TTS local Voice Clone sem HTTP
O `Qwen3TTSBackend` (ou o código equivalente no worker) MUST sintetizar localmente via API Python oficial do pacote `qwen-tts` pinado, usando `generate_voice_clone` (ou equivalente documentado da mesma API) com o checkpoint Base. MUST NÃO usar servidor HTTP/cloud do TTS. Process isolation do worker GPU sob LifecycleManager É permitido e É o hard reclaim oficial entre fases.

#### Scenario: Síntese local Voice Clone
- **WHEN** o pipeline solicita áudio para um `TTSRequest`/SpeechChunk válido com referência resolvida
- **THEN** a síntese ocorre localmente via Voice Clone sem depender de API HTTP TTS

#### Scenario: Worker isolado permitido
- **WHEN** o orquestrador executa a fase TTS
- **THEN** a síntese MAY ocorrer em processo worker filho isolado controlado pelo LifecycleManager

### Requirement: Modelo Base pinado via ModelManager
O backend MUST carregar pesos obtidos via ModelManager para o logical id `qwen3-tts`, repositório `Qwen/Qwen3-TTS-12Hz-0.6B-Base`, com revision pinada (nunca `main`). Arquivos obrigatórios MUST ser validados pelo manager.

#### Scenario: Worker carrega path pinado
- **WHEN** o worker TTS inicia com cache íntegro de `qwen3-tts`
- **THEN** o engine é inicializado a partir desse path/revision sem baixar um checkpoint flutuante

### Requirement: Voice Clone reutiliza referências do registry
O backend MUST resolver `voice_id` via o mecanismo existente de voz (`resolve_voice_dir` / VoiceRegistry) e usar `reference.wav` mais transcript alinhado (`reference.txt` ou `.lab`) no Voice Clone. Personagens com refs Parler já persistidas MUST NÃO precisar regeneração só por causa da troca de ator. Ausência de `./references/` do usuário MUST NÃO ser erro quando o registry do livro tem ref pt-BR válida. MUST NÃO usar fallback silencioso para voz de outro idioma, stock bank, ou outro personagem.

#### Scenario: Ref Parler existente clona
- **WHEN** `synthesize` recebe um `voice_id` com `reference.wav` + transcript no registry do `book_id`
- **THEN** retorna `AudioSegment` não vazio sem regenerar a voz no Parler

### Requirement: Emotion preservada sem mapper instruct
O contrato `TTSRequest.emotion` (e metadata equivalente em SpeechChunks/manifest) MUST permanecer. O backend Qwen3-TTS Base MUST NÃO converter `Emotion` em `instruct`, style prompt, tags tipo `[angry]`, ou parâmetros inexistentes na API `generate_voice_clone`. O campo emotion MUST permanecer disponível para metadata, observabilidade e evolução futura.

#### Scenario: Emotion não vira instruct
- **WHEN** um SpeechChunk com `emotion=angry` é sintetizado
- **THEN** a chamada Voice Clone não recebe um parâmetro `instruct`/style derivado de Emotion e a síntese usa o texto do chunk + referência vocal

#### Scenario: Emotion permanece no manifest
- **WHEN** um chunk é particionado a partir de um diálogo com emotion
- **THEN** a metadata do SpeechChunk e o fluxo de domínio preservam o valor de emotion

### Requirement: Expressividade implícita a partir do texto
O ator Qwen3-TTS Base MUST produzir fala com expressividade e prosódia naturais derivadas do conteúdo textual em pt-BR (compreensão semântica do texto), sem exigir controle emocional explícito. O pipeline MUST NÃO tratar “Emotion controla a geração” como requisito deste capability.

#### Scenario: Gate de expressividade implícita
- **WHEN** a mesma `reference.wav` é usada com textos semanticamente distintos representando neutral, angry, sad, happy, fear, excited e whisper, sem instruction/tags Fish/hacks de sampling
- **THEN** a avaliação perceptual registra PASS ou FAIL; PASS implica variação natural suficiente para audiobook; FAIL MUST ser documentado e MUST NÃO inventar Emotion→instruct nesta change

#### Scenario: Gate insuficiente abre follow-up
- **WHEN** o gate conclui `Implicit Expressiveness Gate: FAIL`
- **THEN** a migração técnica do ator permanece válida e uma investigação separada `evaluate-qwen3-tts-explicit-emotion-control` MAY ser aberta; CustomVoice/VoiceDesign MUST NÃO ser adotados automaticamente

### Requirement: Load e reuso do modelo dentro do worker TTS
Os pesos MUST ser assegurados via ModelManager no máximo uma vez por necessidade de download/validação por execução. Dentro de uma invocação do worker TTS, o engine GPU MUST ser reutilizado para a sequência de SpeechChunks enquanto o headroom permanecer seguro segundo o `VRAMGuardian` (pressão real). O orquestrador MUST preferir uma fase TTS contínua com worker residente; MAY encerrar o worker e iniciar outro por fim de fase, pressão real de VRAM, falha controlada, ou teto opcional de residency. MUST NÃO exigir novo download só porque um worker encerrou.

#### Scenario: Múltiplos chunks sem reload no mesmo worker
- **WHEN** vários SpeechChunks são sintetizados na mesma invocação do worker com headroom seguro
- **THEN** a síntese completa sem novo download e sem novo load completo entre esses chunks

### Requirement: Cache de VoiceClonePrompt por voice_id
Quando a API Qwen3-TTS expuser preparação de prompt de clone (`create_voice_clone_prompt` ou equivalente), o worker/backend MUST construir o prompt uma vez por `voice_id` a partir de `reference.wav` + `reference.txt`, cachear no processo, e reutilizar nos chunks subsequentes da mesma voz. O cache MUST ser descartado no `release()` / exit do worker. MUST NÃO reprocessar a mesma referência em cada chunk quando o cache hit for possível.

#### Scenario: Segunda síntese da mesma voz reutiliza prompt
- **WHEN** dois SpeechChunks consecutivos usam o mesmo `voice_id` com API de prompt disponível
- **THEN** `create_voice_clone_prompt` (ou equivalente) não é reexecutado para o segundo chunk

#### Scenario: Cache morre com o worker
- **WHEN** o worker TTS encerra
- **THEN** o cache de VoiceClonePrompt não sobrevive em outro processo

### Requirement: Batching e overlap oficiais quando disponíveis
O worker MUST usar batching/multi-request suportado pela API oficial do Qwen3-TTS quando disponível, priorizando uma instância do modelo. MUST NÃO carregar múltiplas cópias do modelo por padrão. Preparação CPU do próximo request MAY sobrepor a geração GPU atual desde que ordem determinística, resume, e persist-before-reclaim sejam preservados.

#### Scenario: Sem multi-instância por padrão
- **WHEN** a VRAM livre permitiria múltiplas cópias do Qwen3-TTS
- **THEN** o produto não spawna múltiplas instâncias só por folga de VRAM

#### Scenario: Persist-before-reclaim com overlap
- **WHEN** overlap CPU/GPU está ativo
- **THEN** o áudio do chunk N está persistido e o manifest atualizado antes do reclaim e antes de considerar N concluído

### Requirement: Liberação e hard reclaim do worker TTS
O worker TTS SHALL permitir reclaim best-effort entre chunks. O hard reclaim entre fases de modelo MUST ser o exit do worker, verificado pelo orquestrador via medição de VRAM. Pesos em disco via ModelManager MUST permanecer intactos. O baixo consumo de VRAM do Base MUST NÃO remover essas garantias.

#### Scenario: Persist-before-reclaim
- **WHEN** um SpeechChunk é sintetizado com sucesso
- **THEN** o áudio é persistido antes do reclaim best-effort e antes do próximo chunk

#### Scenario: Exit do worker é hard reclaim
- **WHEN** a fase TTS termina ou o worker faz saída controlada
- **THEN** o processo worker encerra e o orquestrador verifica liberação de VRAM antes da próxima fase GPU

### Requirement: Alocador PyTorch com expandable_segments no worker TTS
O processo worker TTS MUST iniciar com `expandable_segments` nas vars de alloc conf aplicáveis (preferir `PYTORCH_HIP_ALLOC_CONF` em ROCm; assegurar `PYTORCH_CUDA_ALLOC_CONF` quando apropriado), salvo override explícito do usuário.

#### Scenario: Worker recebe expandable_segments
- **WHEN** o orquestrador spawna o worker TTS e o usuário não overrideou as vars de alloc conf
- **THEN** o ambiente do filho inclui `expandable_segments:True` na(s) variável(is) aplicáveis

### Requirement: Sem dual-backend nem CosyVoice
O produto MUST NÃO manter fallback Fish em runtime nem integrar CosyVoice como backend. Rollback MUST ser via Git.

#### Scenario: Único backend de produto
- **WHEN** a instalação de produto está completa após esta change
- **THEN** não há dependência runtime de `fish-speech` nem backend CosyVoice registrado
