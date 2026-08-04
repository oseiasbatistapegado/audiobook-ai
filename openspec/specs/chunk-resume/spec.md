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

### Requirement: Mudança de TTS_MAX_CHUNK_CHARS invalida fingerprint de resume
Alterar `TTS_MAX_CHUNK_CHARS` (ou equivalente usado em `chunking_fingerprint`) MUST alterar o fingerprint de chunking. Manifests da fase TTS gravados com fingerprint incompatível MUST NÃO ser reutilizados cegamente: a fase TTS desses artefatos MUST ser regenerada (ou falhar de forma explícita conforme a política de resume já existente). A residência contínua do worker TTS MUST NÃO enfraquecer skip de chunks `completed` válidos sob o mesmo fingerprint.

#### Scenario: Aumentar chunk size força regeneração TTS
- **WHEN** um work-dir possui manifest completed sob fingerprint de `TTS_MAX_CHUNK_CHARS=500` e a execução atual usa `5000`
- **THEN** o sistema não reutiliza cegamente os áudios incompatíveis e trata a fase TTS como inválida para resume cego

#### Scenario: Mesmo fingerprint permite resume com worker residente
- **WHEN** o fingerprint de chunking no manifest coincide com a execução atual e a fase TTS é contínua
- **THEN** chunks `completed` válidos continuam elegíveis a skip/resume

### Requirement: Atualização atômica do progresso por chunk
Após persistir o áudio de um chunk, o sistema MUST atualizar o manifest para refletir completed (ou estado equivalente) antes de considerar o chunk concluído para resume. Fingerprint de configuração/chunking MUST invalidar chunks quando a configuração relevante mudar de forma incompatível.

#### Scenario: Manifest atualizado após persist
- **WHEN** um chunk é sintetizado e o WAV é escrito
- **THEN** o manifest passa a listá-lo como completed com path utilizável em resume

#### Scenario: Mudança de config invalida resume cego
- **WHEN** o fingerprint de chunking/config no manifest não coincide com a execução atual
- **THEN** o sistema não reutiliza cegamente áudios incompatíveis (falha explícita ou regeneração conforme política documentada)

### Requirement: Pass A resume não re-emite chunks de capítulos já interpretados
Quando um capítulo é pulado por progresso de interpretação válido, o sistema MUST NÃO acrescentar novos SpeechChunks daquele capítulo ao manifest. Chunks já presentes MUST permanecer elegíveis às regras de resume TTS existentes (`pending`/`completed`/fingerprint).

#### Scenario: Skip de interpret preserva manifest do capítulo
- **WHEN** um capítulo está no progresso de interpretação e o generate é reexecutado
- **THEN** o número e identidade dos chunks daquele `chapter_id` no manifest permanecem inalterados por esse skip
