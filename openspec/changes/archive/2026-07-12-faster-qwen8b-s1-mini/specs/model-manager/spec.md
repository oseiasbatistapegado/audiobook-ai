## ADDED Requirements

### Requirement: Registry de pesos Fish open por alias
O ModelManager SHALL expor um registry versionado de identidades Fish **open** endereçáveis por alias CLI (`s1-mini`, `s2-pro` no MVP). Cada alias MUST ter `repository`, `revision` pinada (nunca `main`), `required_files` e um logical id de cache **distinto**. O default do produto MUST ser o alias `s1-mini` (`fishaudio/openaudio-s1-mini` ou equivalente), com layout S1-mini. O alias `s2-pro` MUST preservar a definição pinada de `fishaudio/s2-pro` (safetensors + `codec.pth`, etc.).

#### Scenario: ensure_model S1-mini
- **WHEN** `ensure_model` é chamado para o logical id do alias `s1-mini` sem cache íntegro
- **THEN** o hub é chamado com o repositório S1-mini e a revision pinada, não `main`

#### Scenario: ensure_model s2-pro
- **WHEN** `ensure_model` é chamado para o logical id do alias `s2-pro` sem cache íntegro
- **THEN** o hub é chamado com `fishaudio/s2-pro` e a revision pinada desse alias

#### Scenario: Caches não se sobrescrevem
- **WHEN** ambos `s1-mini` e `s2-pro` foram assegurados com sucesso
- **THEN** cada um reside em diretório de cache distinto sob o cache root

#### Scenario: Validação exige layout do alias
- **WHEN** o diretório do alias `s1-mini` existe mas faltam arquivos obrigatórios (ex.: `model.pth`)
- **THEN** o manager trata como não pronto e completa/repara o download antes de sucesso

### Requirement: Falha gated Hugging Face é acionável
Se o download do S1-mini falhar por repositório gated / não autenticado, o sistema MUST falhar com mensagem que indique autenticação Hugging Face e aceite dos termos do modelo (não um traceback opaco como único sinal).

#### Scenario: 401 gated sem token
- **WHEN** `ensure_model` para o alias `s1-mini` recebe erro de acesso gated/não autorizado do Hub
- **THEN** a falha reportada menciona login HF / aceite do modelo S1-mini
