## MODIFIED Requirements

### Requirement: Detecção de crescimento progressivo por janela deslizante
Após cada SpeechChunk bem-sucedido, o sistema MUST registrar o system free VRAM pós-reclaim. Com janela configurável das últimas `K` amostras (default **3**) e limiar `N` MiB (default **256**), o worker MUST emitir saída `controlled_restart_needed` quando free cair pelo menos `N` MiB ao longo da janela e a tendência for monotonicamente ou consistentemente descendente. Um único sample anômalo MUST NÃO disparar restart. Independente da tendência, se o próximo chunk não satisfizer `before_chunk_target_mib` após reclaim, o worker MUST reiniciar de forma controlada. Esses sinais do guardian MUST ser o mecanismo primário de hard reclaim mid-fase do Fish Speech quando o teto opcional de residency estiver desabilitado. O sistema MUST NÃO esperar violar `hard_floor_mib` nem OOM para considerar degradação.

#### Scenario: Tendência sustentada dispara restart
- **WHEN** as últimas K amostras pós-reclaim mostram queda acumulada ≥ N MiB com tendência descendente consistente
- **THEN** o worker encerra com `controlled_restart_needed` sem sintetizar o próximo chunk

#### Scenario: Sample isolado não reinicia
- **WHEN** uma única amostra pós-reclaim cai mas a janela não satisfaz queda ≥ N com tendência consistente
- **THEN** o worker não dispara restart só por esse sample

#### Scenario: Target de chunk força restart imediato
- **WHEN** após reclaim o próximo chunk não atinge `before_chunk_target_mib`
- **THEN** o worker faz saída controlada imediatamente, mesmo sem tendência completa na janela

#### Scenario: Headroom estável permite continuar residente
- **WHEN** após vários chunks o free pós-reclaim permanece acima de `before_chunk_target_mib` e a janela K/N não indica tendência descendente ≥ N
- **THEN** o guardian NÃO exige hard reclaim e o worker MAY continuar sintetizando na mesma invocação
