## ADDED Requirements

### Requirement: Interpretação em duas passagens (cast então diarização)
Para cada capítulo, o backend LLM MUST (1) resolver o chapter cast via Pass 1 de cast discovery e (2) somente então interpretar cada unidade com Pass 2. Pass 2 MUST receber o speaker set fechado `narrator` ∪ ids classificados como falantes no chapter cast (`speaker` e, se existir, `possible_speaker`) e MUST NÃO descobrir novos `speaker_id` fora desse conjunto no mesmo passo de atribuição. Personagens mentioned-only MUST NÃO ser speakers válidos na Pass 2.

#### Scenario: Pass 2 vê speaker set fechado
- **WHEN** uma unidade é interpretada após Pass 1
- **THEN** o prompt/contexto de Pass 2 inclui a lista explícita de speaker ids permitidos derivados dos falantes do chapter cast (não dos mentioned-only)

#### Scenario: Mentioned-only excluído do speaker set
- **WHEN** Pass 1 classifica `manabu_horikita` como mentioned e `suzune_horikita` como speaker
- **THEN** o speaker set inclui `suzune_horikita` e `narrator`, e NÃO inclui `manabu_horikita`

#### Scenario: Speaker fora do conjunto rejeitado
- **WHEN** Pass 2 emite um `speaker_id` que não resolve para `narrator` nem para o speaker set do capítulo
- **THEN** a resposta falha validação/QA e entra no fluxo de retry (não é cacheada como sucesso)

### Requirement: Narrator não é fallback de incerteza
O prompt e o contrato de Pass 2 MUST tratar `narrator` como narração (incluindo prosa em 1ª pessoa sem fala explícita). Fala explícita / speech-like MUST ser atribuída a um membro do speaker set (ou ao id do protagonista quando for fala do POV), NÃO a `narrator` por incerteza. O sistema MUST NÃO converter silenciosamente diálogo de speaker desconhecido/omitido em `narrator`.

#### Scenario: Diálogo de personagem conhecido não vira narrator
- **WHEN** o speaker set contém `blond_boy` e o texto tem fala do garoto loiro
- **THEN** uma resposta válida atribui essa fala a `blond_boy` (ou alias resolvido), não a `narrator`

#### Scenario: Prosa em 1ª pessoa permanece narrator
- **WHEN** o turno é prosa reflexiva em 1ª pessoa sem fala explícita
- **THEN** o speaker permanece `narrator`

### Requirement: Pass 2 não cria personagens novos via story_updates de speakers
Pass 2 MUST NÃO introduzir novos personagens falantes em `story_updates.characters` como substituto da Pass 1. Atualizações mínimas de aliases MAY ser permitidas apenas para ids já presentes no chapter cast/story, se o schema atual exigir; a descoberta primária de novos falantes MUST ter ocorrido na Pass 1.

#### Scenario: story_updates de Pass 2 não inventa falante novo
- **WHEN** Pass 2 retorna JSON válido
- **THEN** nenhum `speaker_id` de diálogo depende de um personagem criado somente nessa resposta Pass 2 fora do chapter cast prévio

### Requirement: Gate de colapso de diálogo em narrator
Além do detector de dominance em speaker não-narrator, o checker de diarização MUST rejeitar o modo de falha em que há evidência de múltiplos falantes candidatos no speaker set/texto e a maior parte dos turnos speech-like está atribuída a `narrator`. A falha MUST usar prefixo identificável (ex. `speaker QA narrator-collapse`). O checker MUST NÃO exigir segundo modelo LLM. Limiares MUST ser configuráveis com defaults de produto documentados. A fixture de regressão derivada de `ch-005` (cena do ônibus) MUST ser coberta por teste obrigatório.

#### Scenario: Colapso em narrator rejeitado
- **WHEN** a unidade tem ≥2 falantes candidatos no speaker set, volume mínimo de turnos speech-like, e fração dominante desses turnos com speaker `narrator`
- **THEN** o checker falha com erro `narrator-collapse` e a resposta NÃO é aceita como interpretação final

#### Scenario: Monólogo sem multi-speaker passa
- **WHEN** o speaker set / evidência local não indica múltiplos falantes
- **THEN** o invariante de narrator-collapse NÃO rejeita só porque há muitos turnos `narrator`

#### Scenario: Fixture ch-005 rejeita colapso conhecido
- **WHEN** o checker recebe a fixture de regressão derivada do `ch-005` com falas de `blond_boy`/`elderly_woman`/schoolgirl colapsadas em `narrator`
- **THEN** o checker falha

### Requirement: Retry de narrator-collapse sem refresh de Pass 1
Quando o gate de narrator-collapse falha, o MVP MUST retentar apenas a Pass 2 com o **mesmo** chapter cast / speaker set fechado, incluindo o erro de QA e instrução de correção de atribuição. O MVP MUST NÃO invalidar automaticamente nem reexecutar Pass 1 por causa de narrator-collapse. Refresh automático de cast discovery após falha de diarização fica explicitamente fora do MVP. Se as tentativas Pass 2 se esgotarem, o sistema MUST abortar a unidade com a semântica de falha de interpretação já existente.

#### Scenario: Narrator-collapse retenta Pass 2 com o mesmo cast
- **WHEN** Pass 2 falha com `speaker QA narrator-collapse`
- **THEN** a próxima tentativa Pass 2 reutiliza o mesmo speaker set fechado e inclui o feedback de QA

#### Scenario: Narrator-collapse não dispara Pass 1
- **WHEN** ocorre narrator-collapse durante Pass 2
- **THEN** o sistema NÃO reexecuta cast discovery automaticamente nessa falha

#### Scenario: Retries esgotados abortam a unidade
- **WHEN** todas as tentativas Pass 2 após narrator-collapse continuam inválidas
- **THEN** o processamento da unidade aborta com erro contextual (sem aceitar o colapso)

### Requirement: Política de cache/diarização bumpada para two-pass
A versão de política de diarização MUST ser incrementada de forma que caches de interpretação single-pass anteriores NÃO sejam reutilizados como sucesso sob a arquitetura two-pass.

#### Scenario: Cache single-pass antigo não é hit
- **WHEN** existe cache de interpret gerado sob política anterior à two-pass
- **THEN** a execução atual com a nova política NÃO trata esse cache como resposta válida de Pass 2

## MODIFIED Requirements

### Requirement: Prompt exige atribuição correta de speakers
O arquivo de prompt de interpretação sob `llm/prompts/` MUST instruir regras explícitas de diarização compatíveis com `qwen3:8b`: prosa narrativa (incluindo 1ª pessoa) MUST usar speaker `narrator`; fala explícita do POV/protagonista MUST usar o `character_id` do protagonista (não `narrator`); cada turno de fala MUST ter exatamente um speaker; MUST NÃO misturar falas de personagens distintos no mesmo `dialogues[].text`; speakers MUST ser escolhidos do speaker set fechado (`narrator` ∪ falantes do chapter cast da Pass 1); MUST NÃO inventar novos `speaker_id` fora desse conjunto; MUST NÃO usar mentioned-only como speaker; pistas de atribuição no texto-fonte MUST coincidir com o speaker do turno e MUST NÃO ser copiadas para dentro do `dialogues[].text` falado (a voz do turn identifica o falante); `narrator` MUST NÃO ser usado como fallback para fala não resolvida. O prompt MAY esclarecer que `speaker_id` identifica papel narrativo e NÃO implica por si só uma `voice_id` distinta.

#### Scenario: Prompt carrega regras de diarização
- **WHEN** o backend carrega o prompt de interpretação para uma chamada Ollama Pass 2
- **THEN** o texto do prompt inclui prosa/1ª pessoa → `narrator`, fala do POV → protagonist id, um speaker por turno, proibição de misturar falantes no mesmo `text`, proibição de speech-tags de atribuição no texto falado, speaker set fechado (só falantes), e proibição de `narrator` como fallback de diálogo

#### Scenario: Narração em 1ª pessoa não usa o protagonist id
- **WHEN** o texto é prosa em 1ª pessoa sem fala explícita entre aspas/travessão
- **THEN** a resposta válida atribui esse segmento a `narrator`, não ao `character_id` do protagonista

#### Scenario: Prompt lista speakers permitidos
- **WHEN** Pass 2 é invocada com chapter falantes `blond_boy` e `office_lady`
- **THEN** o contexto enviado ao modelo inclui esses ids (além de `narrator`) como speakers permitidos
