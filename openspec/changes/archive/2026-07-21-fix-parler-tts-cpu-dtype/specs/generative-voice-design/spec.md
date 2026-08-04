## MODIFIED Requirements

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
