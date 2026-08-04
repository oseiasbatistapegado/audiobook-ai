## MODIFIED Requirements

### Requirement: Verificar imports do runtime TTS
Quando o backend TTS for Qwen3-TTS, o preflight SHALL verificar que o runtime necessário (`torch` e o pacote `qwen_tts` / equivalente pinado) é importável. Se ausente, MUST falhar com a sequência de instalação documentada do extra TTS Qwen3, sem iniciar download de pesos. O preflight MUST NÃO exigir `fish_speech`.

#### Scenario: qwen_tts não instalado
- **WHEN** `import qwen_tts` (ou equivalente documentado) falha no preflight
- **THEN** a CLI aborta com instruções de install e não chama `ModelManager.ensure_model` para TTS

#### Scenario: fish_speech não é requisito
- **WHEN** `fish_speech` não está instalado mas o runtime Qwen3-TTS está importável
- **THEN** o preflight TTS NÃO falha por ausência de Fish

## ADDED Requirements

### Requirement: Preflight valida independência Parler/DAC sem Fish
Quando Voice Design Parler estiver habilitado no caminho de produto, o preflight (ou teste de instalação documentado) SHALL verificar que as dependências de decode necessárias ao Parler estão disponíveis sem exigir `fish-speech`.

#### Scenario: Parler ready sem Fish
- **WHEN** o preflight/checagem de Voice Design roda com Parler instalado e `fish-speech` ausente
- **THEN** a checagem de dependências de codec/DAC do Parler passa ou falha com instrução de install do extra Parler autossuficiente (nunca “instale fish-speech”)
