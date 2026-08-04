## Purpose

Voice Design generativo que cria identidades vocais sintéticas únicas em pt-BR por personagem (sem catálogo finito), com materialização de referência para Qwen3-TTS Voice Clone.

## Requirements

### Requirement: Voice Design gera identidade sintética única
O sistema SHALL gerar, para cada personagem relevante sem voz persistida no escopo do audiobook, uma identidade vocal sintética **nova** via backend de voice design (não seleção de catálogo finito). A identidade MUST ser condicionada ao `VoiceProfile` semântico (quando presente) e a um seed determinístico distinto por `character_id`.

#### Scenario: Dois personagens similares recebem identidades distintas
- **WHEN** dois personagens com `VoiceProfile` semanticamente similar (ex. mesmo gender/age/pitch) mas `character_id` diferentes são gerados no mesmo livro
- **THEN** as referências resultantes são identidades de speaker perceptualmente distintas (não a mesma base copiada/renomeada)

#### Scenario: Sem áudio manual do usuário
- **WHEN** um personagem novo precisa de voz e não há override em `./references/`
- **THEN** o sistema gera a referência automaticamente sem exigir WAV fornecido pelo usuário

### Requirement: Referência canônica pt-BR materializada
Após criar a identidade, o Voice Design MUST materializar áudio de referência falando português brasileiro natural, com texto alinhado (`reference.txt` ou `.lab`) correspondente ao conteúdo falado. Generic Portuguese / pt-PT inaceitável como resultado de sucesso. A referência MUST ser utilizável pelo ator TTS de produto (Qwen3-TTS Voice Clone).

#### Scenario: Metadata language pt-BR
- **WHEN** a geração conclui com sucesso
- **THEN** `GeneratedVoice.language` e metadata persistida declaram `pt-BR` e a passagem canônica está em português brasileiro

#### Scenario: Duração adequada para clonagem
- **WHEN** a referência é gerada para uso pelo ator TTS
- **THEN** o áudio respeita `VOICE_REF_MAX_SECONDS` (default **6.0** nesta change) e tem texto alinhado

### Requirement: Backend MVP Parler-TTS pt-BR
A implementação primária MUST ser o adapter Parler-TTS pt-BR pinado. O extra/dependências de Voice Design MUST ser autossuficientes: instalar suporte Parler + suporte Qwen3-TTS **sem** instalar `fish-speech` MUST permitir Voice Design funcional. A dependência de decode efetivamente usada pelo runtime Parler pinado MUST ser descoberta em ambiente sem Fish, declarada diretamente no extra `voice-parler`, e pinada; MUST NÃO permanecer como transitiva implícita via `fish-speech`.

#### Scenario: Parler sem fish-speech
- **WHEN** o ambiente tem extras Parler e Qwen3-TTS instalados e `fish-speech` ausente
- **THEN** o worker/gerador Parler consegue materializar `reference.wav` válido

#### Scenario: Gate composto de remoção do Fish
- **WHEN** `fish-speech` não está instalado, Parler gera `reference.wav`, e Qwen3-TTS clona essa referência com sucesso
- **THEN** o gate de remoção do Fish passa e a dependência DAC/decode está declarada no extra Parler

#### Scenario: Factory resolve gerador generativo
- **WHEN** a configuração default de voice generator está ativa
- **THEN** o factory retorna o gerador Parler, não um gerador Qwen VoiceDesign

### Requirement: Alternativa Qwen só após falha Parler
Qwen3-TTS VoiceDesign MUST NÃO ser adotado nesta change. Avaliação de Qwen como Voice Designer MUST ocorrer apenas em change separada (`evaluate-qwen3-tts-voice-design`) após a migração do ator estar estável. Portuguese genérico MUST NÃO ser tratado como prova de pt-BR.

#### Scenario: Voice Design Qwen fora de escopo
- **WHEN** esta change está implementada
- **THEN** o hot path de produto continua usando Parler para Voice Design e Qwen3-TTS Base apenas como ator Voice Clone

### Requirement: Fase dedicada e unload do modelo de design
O modelo de Voice Design MUST rodar em fase dedicada (worker isolado) para vozes faltantes do livro e MUST NÃO ser invocado por cada segmento/chunk de diálogo. Após gerar as refs faltantes, o worker MUST encerrar; o orquestrador MUST verificar liberação de VRAM antes de carregar/spawnar o worker TTS. Unload apenas in-process MAY existir dentro do worker, mas o hard reclaim oficial entre Voice Design e TTS É o exit do worker.

#### Scenario: Batch antes do TTS com worker
- **WHEN** o pipeline identifica N personagens sem voz no `book_id` atual
- **THEN** spawna o worker de Voice Design, gera as N refs, persiste, encerra o worker, verifica release de VRAM, e só então spawna o worker TTS para síntese

#### Scenario: Sem Parler residente durante TTS
- **WHEN** o worker TTS está ativo
- **THEN** o modelo de Voice Design não está carregado em nenhum processo controlado pelo projeto

### Requirement: Fase dedicada e unload do modelo de design com batch pós-interpretação
O modelo de Voice Design MUST rodar em fase dedicada (worker isolado) para vozes faltantes do livro e MUST NÃO ser invocado por cada segmento/chunk de diálogo. Após gerar as refs faltantes, o worker MUST encerrar; o orquestrador MUST verificar liberação de VRAM antes de carregar/spawnar o worker TTS. Unload apenas in-process MAY existir dentro do worker, mas o hard reclaim oficial entre Voice Design e TTS É o exit do worker.

Todas as vozes faltantes devem ser processadas em um **único batch** após a interpretação completa de todos os capítulos, eliminando spawns redundantes. O pipeline NÃO deve invocar `run_voice_design_phase` dentro do loop de capítulos.

As vozes faltantes são coletadas durante a iteração dos capítulos e
processadas em um único spawn após o loop de interpretação.

#### Scenario: Batch antes do TTS com worker
- **WHEN** o pipeline identifica N personagens sem voz no `book_id` atual
- **THEN** spawna o worker de Voice Design, gera as N refs, persiste, encerra o worker, verifica release de VRAM, e só então spawna o worker TTS para síntese

#### Scenario: Voice design batchado após interpretação
- **WHEN** o pipeline completa a interpretação de todos os N capítulos
- **THEN** um único worker de Voice Design é spawned com todos os `character_ids` faltantes

#### Scenario: Sem voice-design no loop de capítulos
- **WHEN** o pipeline itera `for chapter in book.chapters`
- **THEN** nenhum `run_voice_design_phase` é chamado dentro do loop

#### Scenario: Resume mantém voice-design batchado
- **WHEN** o pipeline resume de `interpret_progress.json` e alguns capítulos já foram interpretados
- **THEN** o voice-design batch processa apenas os caracteres novos descobertos nos capítulos restantes

### Requirement: Adapter traduz VoiceProfile sem expor backend ao LLM
O adapter do gerador MUST traduzir `VoiceProfile` estruturado para o formato de condicionamento do backend (ex. prompt textual Parler). O prompt do LLM MUST NÃO exigir parâmetros específicos de Parler/Qwen.

#### Scenario: Perfil estruturado vira condicionamento
- **WHEN** um personagem possui `voice_profile` com gender/pitch/energy/personality
- **THEN** o adapter produz condicionamento backend-específico e o pipeline permanece agnóstico à API do modelo

### Requirement: Backend MVP Parler-TTS pt-BR com VRAM otimizado
O modelo Parler-TTS mini SHALL ser carregado com **precision condicional ao dispositivo**: `torch_dtype=torch.float16` em GPU (CUDA/ROCm) para limitar o pico de VRAM a ~1.2 GB de pesos, e `torch_dtype=torch.float32` em CPU para evitar dtype mismatch com buffers não-persistentes (ex. `inv_freq` no `ParlerTTSRotaryEmbedding`). O dtype é determinado pelo device resolvido antes de `from_pretrained`, não pelo parâmetro `device` separado.

O threshold de carregamento `PARLER_BEFORE_LOAD_TARGET_MIB` deve ser **4096 MiB**
(4 GB), valor calibrado para GPUs de 24 GB onde o Ollama ocupa ~17.5 GB
e deixa ~7 GB livres. Em CPU, este threshold não se aplica.

#### Scenario: Parler carrega em FP16 em GPU
- **WHEN** o gerador Parler instancia o modelo via `from_pretrained` e o device resolvido é CUDA ou ROCm
- **THEN** o modelo é carregado com `torch_dtype=torch.float16` e ocupa ~1.2 GB de pesos

#### Scenario: Parler carrega em FP32 em CPU
- **WHEN** o gerador Parler instancia o modelo via `from_pretrained` e o device resolvido é CPU
- **THEN** o modelo é carregado com `torch_dtype=torch.float32` e o dtype de todos os pesos e activations é consistente

#### Scenario: Geração funciona em CPU
- **WHEN** o gerador Parler roda em CPU e invoca `model.generate()` com `input_ids` e `prompt_input_ids`
- **THEN** a geração conclui sem erro de dtype mismatch (`c10::Half != float`)

#### Scenario: Gate de VRAM passa em GPU de 24 GB
- **WHEN** o Ollama é desligado e o system-free VRAM reportado é ~7000 MiB
- **THEN** `can_load_backend("parler")` retorna `(True, None)` com `PARLER_BEFORE_LOAD_TARGET_MIB=4096`

#### Scenario: Threshold configurável via CLI
- **WHEN** o usuário passa `--parler-load-target-mib` ou seta a variável de ambiente correspondente
- **THEN** o valor é passado para `build_guardian()` e usado pelo `GuardianConfig.load_targets_mib`
