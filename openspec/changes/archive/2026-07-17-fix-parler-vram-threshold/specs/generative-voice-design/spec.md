## MODIFIED Requirements

### Requirement: Backend MVP Parler-TTS pt-BR com gate de spike

O modelo Parler-TTS mini **MUST ser carregado em FP16** (`torch_dtype=torch.float16`
durante `from_pretrained`) para limitar o pico de VRAM a ~1.2 GB de pesos,
facilitando o carregamento em GPUs com orçamento restrito (24 GB).

O threshold de carregamento `PARLER_BEFORE_LOAD_TARGET_MIB` deve ser **4096 MiB**
(4 GB), valor calibrado para GPUs de 24 GB onde o Ollama ocupa ~17.5 GB
e deixa ~7 GB livres.

#### Scenario: Parler carrega em FP16
- **WHEN** o gerador Parler instancia o modelo via `from_pretrained`
- **THEN** o modelo é carregado com `torch_dtype=torch.float16` e ocupa ~1.2 GB de pesos

#### Scenario: Gate de VRAM passa em GPU de 24 GB
- **WHEN** o Ollama é desligado e o system-free VRAM reportado é ~7000 MiB
- **THEN** `can_load_backend("parler")` retorna `(True, None)` com `PARLER_BEFORE_LOAD_TARGET_MIB=4096`

#### Scenario: Threshold configurável via CLI
- **WHEN** o usuário passa `--parler-load-target-mib` ou seta a variável de ambiente correspondente
- **THEN** o valor é passado para `build_guardian()` e usado pelo `GuardianConfig.load_targets_mib`

### Requirement: Fase dedicada e unload do modelo de design

O sistema **MUST processar todas as vozes faltantes em um único batch**
após a interpretação completa de todos os capítulos, eliminando spawns
redundantes por capítulo. O pipeline NÃO deve invocar `run_voice_design_phase`
dentro do loop de capítulos.

As vozes faltantes são coletadas durante a iteração dos capítulos e
processadas em um único spawn após o loop de interpretação.

#### Scenario: Voice design batchado após interpretação
- **WHEN** o pipeline completa a interpretação de todos os N capítulos
- **THEN** um único worker de Voice Design é spawned com todos os `character_ids` faltantes

#### Scenario: Sem voice-design no loop de capítulos
- **WHEN** o pipeline itera `for chapter in book.chapters`
- **THEN** nenhum `run_voice_design_phase` é chamado dentro do loop

#### Scenario: Resume mantém voice-design batchado
- **WHEN** o pipeline resume de `interpret_progress.json` e alguns capítulos já foram interpretados
- **THEN** o voice-design batch processa apenas os caracteres novos descobertos nos capítulos restantes
