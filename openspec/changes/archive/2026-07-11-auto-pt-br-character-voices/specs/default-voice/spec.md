## MODIFIED Requirements

### Requirement: Empacotar voz narrator padrão
O sistema SHALL incluir assets de voz padrão sob `assets/voices/narrator/` (ou path equivalente documentado no pacote) contendo áudio de referência e arquivo `.lab`/texto alinhado compatível com Fish Speech, suficientes para síntese sem configuração manual do usuário. A voz narrator empacotada MUST ser **português brasileiro (`pt-BR`)** (metadata e conteúdo falado de referência), MUST NÃO ser um clipe de smoke em inglês, e MUST permanecer dedicada ao narrador no fluxo automático.

#### Scenario: Assets presentes no checkout
- **WHEN** o repositório é clonado e as deps TTS estão instaladas
- **THEN** os arquivos de referência da voz `narrator` estão disponíveis no path empacotado documentado

#### Scenario: Narrator empacotado é pt-BR
- **WHEN** os assets `assets/voices/narrator/` são inspecionados
- **THEN** o metadata associado declara `language=pt-BR` e o texto de referência (`.lab`/`.txt`) está em português brasileiro

### Requirement: Resolver voz padrão automaticamente
O `FishSpeechBackend` (via resolução de vozes compartilhada) MUST resolver a voz `narrator` a partir do registry/cache ou dos assets empacotados quando o usuário não fornece um diretório `references/` próprio. A síntese MUST NÃO exigir que o usuário copie arquivos de voz manualmente para o smoke MVP. A resolução automática MUST NÃO cair para uma referência conhecida como não-pt-BR.

#### Scenario: Synthesize sem references do usuário
- **WHEN** `FishSpeechBackend.synthesize` é chamado com `voice_id` `narrator` (ou fallback documentado pt-BR para narrator) e não há override de referências do usuário
- **THEN** o backend usa registry ou assets empacotados pt-BR e retorna um `AudioSegment` não vazio (em ambiente com engine/pesos válidos)

#### Scenario: Override do usuário
- **WHEN** o usuário fornece referências sob `./references/<voice_id>/` (ou path injetado nos testes)
- **THEN** o backend preferirá as referências do usuário em relação ao registry/cache e aos assets empacotados para esse `voice_id`
