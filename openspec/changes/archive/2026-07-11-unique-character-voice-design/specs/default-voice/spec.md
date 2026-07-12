## MODIFIED Requirements

### Requirement: Empacotar voz narrator padrão
O sistema MAY manter assets empacotados de narrator apenas como ferramenta de desenvolvimento/teste. Para o produto MVP de voice design, o narrator MUST receber identidade dedicada **gerada** (ou explicitamente configurada pelo usuário) em pt-BR — MUST NÃO depender de um slot de banco finito como solução primária de sucesso.

#### Scenario: Narrator gerado no fluxo automático
- **WHEN** um audiobook novo precisa de voz de narrator sem override do usuário
- **THEN** o Voice Design gera e persiste uma identidade narrator pt-BR scoped ao `book_id`

#### Scenario: Narrator empacotado não substitui geração
- **WHEN** apenas assets empacotados de banco existem e a política generativa está ativa
- **THEN** o sistema NÃO considera a mera cópia do asset empacotado como cumprimento do requisito de identidade sintética do narrator (salvo override explícito documentado)

### Requirement: Resolver voz padrão automaticamente
A resolução compartilhada MUST preferir registry do livro (`voices/<book_id>/narrator/`) ou override do usuário. A síntese MUST NÃO exigir cópia manual de refs. MUST NÃO cair para referência não-pt-BR. MUST NÃO usar voz de personagem como narrator.

#### Scenario: Synthesize narrator sem references manuais
- **WHEN** `synthesize` é chamado com `voice_id` narrator e existe ref pt-BR gerada no registry do livro
- **THEN** o backend usa essa ref e retorna áudio não vazio (com engine válido)

#### Scenario: Override do usuário
- **WHEN** o usuário fornece `./references/narrator/`
- **THEN** o backend preferirá o override do usuário
