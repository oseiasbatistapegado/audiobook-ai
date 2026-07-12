## Purpose

Voice Design generativo que cria identidades vocais sintéticas únicas em pt-BR por personagem (sem catálogo finito), com materialização de referência para o Fish Speech.

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
Após criar a identidade, o Voice Design MUST materializar áudio de referência falando português brasileiro natural, com texto alinhado (`reference.txt` ou `.lab`) correspondente ao conteúdo falado. Generic Portuguese / pt-PT inaceitável como resultado de sucesso.

#### Scenario: Metadata language pt-BR
- **WHEN** a geração conclui com sucesso
- **THEN** `GeneratedVoice.language` e metadata persistida declaram `pt-BR` e a passagem canônica está em português brasileiro

#### Scenario: Duração adequada para clonagem
- **WHEN** a referência é gerada para uso pelo Fish Speech
- **THEN** o áudio tem duração na faixa calibrada experimentalmente (alvo ~10–30s) e texto alinhado

### Requirement: Backend MVP Parler-TTS pt-BR com gate de spike
A implementação primária candidata MUST ser um adapter `ParlerVoiceGenerator` sobre o modelo Parler-TTS pt-BR documentado no design (`freds0/parler-tts-mini-v1.1-ptbr` ou sucessor pinado). O backend MUST NÃO ser tratado como production-ready até o spike local passar os critérios de aceite (pt-BR, unicidade, aderência semântica aproximada, export de ref, Fish Speech preserva distinção, ROCm/VRAM).

#### Scenario: Factory resolve gerador generativo
- **WHEN** a configuração default de voice generator está ativa após seleção do backend
- **THEN** o factory retorna o gerador generativo escolhido (Parler ou Qwen pós-spike), não `BankVoiceGenerator`

#### Scenario: Spike Carlos vs João
- **WHEN** o spike gera duas vozes com perfis similares, seeds distintos, mesma frase canônica pt-BR, e passa ambas pelo Fish Speech
- **THEN** as saídas clonadas permanecem perceptualmente distintas e ambas em pt-BR aceitável

### Requirement: Alternativa Qwen só após falha Parler
Qwen3-TTS VoiceDesign MAY ser avaliado e adotado **somente** se o spike Parler falhar critérios críticos. Portuguese genérico MUST NÃO ser tratado como prova de pt-BR.

#### Scenario: Parler falha unicidade ou pt-BR
- **WHEN** o spike Parler falha unicidade, pt-BR, ou preservação no Fish Speech
- **THEN** a equipe executa o spike equivalente Qwen antes de declarar outro default; banco fixo NÃO é substituto de sucesso

### Requirement: Fase dedicada e unload do modelo de design
O modelo de Voice Design MUST rodar em fase dedicada (worker isolado) para vozes faltantes do livro e MUST NÃO ser invocado por cada segmento/chunk de diálogo. Após gerar as refs faltantes, o worker MUST encerrar; o orquestrador MUST verificar liberação de VRAM antes de carregar/spawnar o Fish Speech. Unload apenas in-process MAY existir dentro do worker, mas o hard reclaim oficial entre Voice Design e Fish Speech É o exit do worker.

#### Scenario: Batch antes do TTS com worker
- **WHEN** o pipeline identifica N personagens sem voz no `book_id` atual
- **THEN** spawna o worker de Voice Design, gera as N refs, persiste, encerra o worker, verifica release de VRAM, e só então spawna o Fish Speech worker para síntese

#### Scenario: Sem Parler residente durante Fish
- **WHEN** o Fish Speech worker está ativo
- **THEN** o modelo de Voice Design não está carregado em nenhum processo controlado pelo projeto

### Requirement: Adapter traduz VoiceProfile sem expor backend ao LLM
O adapter do gerador MUST traduzir `VoiceProfile` estruturado para o formato de condicionamento do backend (ex. prompt textual Parler). O prompt do LLM MUST NÃO exigir parâmetros específicos de Parler/Qwen.

#### Scenario: Perfil estruturado vira condicionamento
- **WHEN** um personagem possui `voice_profile` com gender/pitch/energy/personality
- **THEN** o adapter produz condicionamento backend-específico e o pipeline permanece agnóstico à API do modelo
