## ADDED Requirements

### Requirement: Alocador PyTorch com expandable_segments no worker Fish
O processo worker Fish Speech MUST iniciar com configuração de alocador que habilite `expandable_segments` para reduzir OOM por fragmentação mid-fase (HIP/CUDA), salvo se o ambiente do usuário já definir explicitamente a variável correspondente. O orquestrador/spawn MUST preferir `PYTORCH_HIP_ALLOC_CONF` em stacks ROCm e MUST também assegurar `PYTORCH_CUDA_ALLOC_CONF` com `expandable_segments:True` quando apropriado e ainda não definido. Unexpected OOM MUST continuar sendo classificado e reportado; esta config MUST NÃO silenciar falhas.

#### Scenario: Worker recebe expandable_segments
- **WHEN** o orquestrador spawna o worker Fish e o usuário não overrideou as vars de alloc conf
- **THEN** o ambiente do processo filho inclui `expandable_segments:True` na(s) variável(is) de alloc conf aplicáveis

#### Scenario: Override do usuário preservado
- **WHEN** o usuário já exportou `PYTORCH_HIP_ALLOC_CONF` ou `PYTORCH_CUDA_ALLOC_CONF` antes do spawn
- **THEN** o valor do usuário é preservado (não sobrescrito às cegas pelo pipeline)
