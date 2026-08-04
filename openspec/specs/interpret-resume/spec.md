## Purpose

Resume do Pass A (interpretação LLM): pular capítulos já concluídos no restart, com progresso book-scoped e bootstrap seguro para work-dirs legados.

## Requirements

### Requirement: Progresso de interpretação book-scoped
O sistema SHALL persistir o conjunto de capítulos cuja fase de interpretação (Pass A) concluiu com sucesso sob `work/<book_id>/` (ex.: `interpret_progress.json`). A gravação MUST ocorrer somente após interpretação bem-sucedida — incluindo Pass 1 (cast discovery) e Pass 2 (todas as unidades) —, aplicação/persistência de `story` updates daquele capítulo, e merge dos SpeechChunks no manifest (quando houver diálogos). O artefato MUST registrar identificadores de política/modelo usados (modelo Ollama + versões de política de adaptação/diarização) para invalidação.

#### Scenario: Capítulo marcado após sucesso
- **WHEN** o pipeline termina Pass A de um capítulo sem erro
- **THEN** o `chapter_id` passa a constar no progresso persistido book-scoped

#### Scenario: Crash mid-capítulo não marca progresso
- **WHEN** a interpretação de um capítulo falha ou o processo interrompe antes do commit de progresso
- **THEN** aquele `chapter_id` MUST NÃO ser tratado como interpretado no restart

### Requirement: Capítulo só marca progresso após discovery + interpret
O progresso de interpretação book-scoped MUST considerar um capítulo concluído somente após Pass 1 (cast discovery) e Pass 2 (todas as unidades de interpretação) terem sucesso, com aplicação/persistência de story updates e merge de SpeechChunks no manifest quando aplicável. Falha em Pass 1 ou em qualquer unidade Pass 2 MUST NÃO marcar o `chapter_id` como interpretado.

#### Scenario: Falha na discovery não marca progresso
- **WHEN** Pass 1 falha após esgotar tentativas
- **THEN** o `chapter_id` NÃO entra no progresso persistido

#### Scenario: Falha numa unidade Pass 2 não marca progresso
- **WHEN** Pass 1 ok mas uma unidade Pass 2 falha
- **THEN** o `chapter_id` NÃO é tratado como interpretado no restart

### Requirement: Skip de capítulos já interpretados no restart
Em reexecução de `generate` sobre o mesmo `book_id`/work-dir, capítulos listados no progresso de interpretação (e ainda válidos sob o mesmo modelo/políticas gravadas) MUST ser pulados: o sistema MUST NÃO chamar Ollama de novo nem reaplicar `story_updates` nem re-emitar chunks daquele capítulo.

#### Scenario: Resume mid-Pass-A
- **WHEN** os capítulos 1..K estão no progresso e K+1..N não
- **THEN** a retomada interpreta apenas K+1..N e preserva story/manifest de 1..K

#### Scenario: Progress inválido por mudança de política ou modelo
- **WHEN** o progresso gravado refere modelo ou versões de política diferentes da execução atual — incluindo bump que introduz two-pass cast-then-diarize
- **THEN** o sistema NÃO faz skip cego com base nesse progresso (reinterpreta ou invalida o progresso conforme política documentada)

#### Scenario: Progress single-pass não pula após política two-pass
- **WHEN** o progresso foi gravado sob política de diarização anterior à two-pass e a execução atual usa a nova política
- **THEN** os capítulos NÃO são pulados com base nesse progresso antigo

### Requirement: Bootstrap seguro para work-dirs legados
Quando o arquivo de progresso estiver ausente mas o manifest já contiver chunks, o sistema MAY inferir capítulos interpretados a partir dos `chapter_id` presentes no manifest, EXCETO o último `chapter_id` na ordem do livro que aparece no manifest (tratado como potencialmente parcial). Capítulos sem chunks permanecem pendentes de interpretação.

#### Scenario: Manifest parcial sem progress file
- **WHEN** o manifest tem chunks para ch-001..ch-005 e não existe progress file
- **THEN** ch-001..ch-004 MAY ser tratados como interpretados e ch-005 MUST ser re-elegível a interpretação
