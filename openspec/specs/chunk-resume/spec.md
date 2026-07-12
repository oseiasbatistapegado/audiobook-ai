## Purpose

Persistência book-scoped e resume de SpeechChunks via manifest ordenado, para retomar geração sem regenerar áudio já válido.

## Requirements

### Requirement: Namespace book-scoped para artefatos resumíveis
Todo estado interno resumível da geração (story, manifest, áudio de chunks, logs da execução) MUST residir sob `work/<book_id>/`, onde `book_id` é o **BLAKE2b-128 do conteúdo do arquivo de input** (mesma derivação canônica das character voices). Mover ou renomear o source MUST NÃO criar nova identidade. O path do artefato final (M4B) é controlado pelo usuário e MUST NÃO determinar `book_id`. Referências de voz permanecem no registry/cache book-scoped existente.

#### Scenario: Rename do PDF preserva identidade
- **WHEN** o mesmo conteúdo de input é gerado a partir de um path renomeado
- **THEN** `book_id` e o diretório `work/<book_id>/` permanecem os mesmos

#### Scenario: Output path não redefine book_id
- **WHEN** o usuário passa `--output` para um path arbitrário
- **THEN** manifest e chunks continuam sob `work/<book_id>/` derivado do conteúdo do input

### Requirement: Manifest ordenado de SpeechChunks
O sistema SHALL manter um manifest (ex.: `work/<book_id>/manifest.json`) que registra a ordem canônica dos SpeechChunks, status (pending/completed/failed), e caminhos dos artefatos. A ordem de merge e resume MUST vir do manifest, NÃO da ordem de travessia do filesystem.

#### Scenario: Merge segue o manifest
- **WHEN** múltiplos arquivos de áudio de chunk existem sob `work/<book_id>/audio/`
- **THEN** o merge utiliza a sequência registrada no manifest

### Requirement: Skip de chunks válidos já concluídos
Em reinício após crash, OOM controlado, restart de worker ou reexecução do generate sobre o mesmo work-dir, SpeechChunks com artefato válido e entrada completed no manifest MUST ser reutilizados sem regeneração.

#### Scenario: Resume após interrupção
- **WHEN** os chunks 1..K estão completed no manifest e K+1..N pendentes
- **THEN** a retomada regenera apenas os pendentes/inválidos e preserva 1..K

#### Scenario: Chunk inválido é regenerado
- **WHEN** o manifest marca um chunk completed mas o arquivo de áudio está ausente ou inválido
- **THEN** esse chunk é tratado como pendente e regenerado

### Requirement: Atualização atômica do progresso por chunk
Após persistir o áudio de um chunk, o sistema MUST atualizar o manifest para refletir completed (ou estado equivalente) antes de considerar o chunk concluído para resume. Fingerprint de configuração/chunking MUST invalidar chunks quando a configuração relevante mudar de forma incompatível.

#### Scenario: Manifest atualizado após persist
- **WHEN** um chunk é sintetizado e o WAV é escrito
- **THEN** o manifest passa a listá-lo como completed com path utilizável em resume

#### Scenario: Mudança de config invalida resume cego
- **WHEN** o fingerprint de chunking/config no manifest não coincide com a execução atual
- **THEN** o sistema não reutiliza cegamente áudios incompatíveis (falha explícita ou regeneração conforme política documentada)
