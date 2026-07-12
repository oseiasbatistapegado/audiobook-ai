## ADDED Requirements

### Requirement: Empacotar voz narrator padrão
O sistema SHALL incluir assets de voz padrão sob `assets/voices/narrator/` (ou path equivalente documentado no pacote) contendo áudio de referência e arquivo `.lab` compatível com Fish Speech, suficientes para síntese sem configuração manual do usuário.

#### Scenario: Assets presentes no checkout
- **WHEN** o repositório é clonado e as deps TTS estão instaladas
- **THEN** os arquivos de referência da voz `narrator` estão disponíveis no path empacotado documentado

### Requirement: Resolver voz padrão automaticamente
O `FishSpeechBackend` MUST resolver a voz `narrator` a partir dos assets empacotados quando o usuário não fornece um diretório `references/` próprio. A síntese MUST NÃO exigir que o usuário copie arquivos de voz manualmente para o smoke MVP.

#### Scenario: Synthesize sem references do usuário
- **WHEN** `FishSpeechBackend.synthesize` é chamado com `voice_id` `narrator` (ou fallback para narrator) e não há override de referências do usuário
- **THEN** o backend usa os assets empacotados e retorna um `AudioSegment` não vazio (em ambiente com engine/pesos válidos)

#### Scenario: Override do usuário
- **WHEN** o usuário fornece referências sob `./references/<voice_id>/` (ou path injetado nos testes)
- **THEN** o backend preferirá as referências do usuário em relação aos assets empacotados para esse `voice_id`
