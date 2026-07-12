## ADDED Requirements

### Requirement: Mesclar áudio dos capítulos em um único arquivo
O sistema SHALL concatenar os segmentos/capítulos gerados em um único arquivo de saída usando ffmpeg. O formato de saída MUST ser inferido da extensão de `--output`. O default do produto MUST ser **M4B**; MP3 MUST permanecer suportado quando o usuário especificar `.mp3`, mas MUST NÃO ser o fallback primário automático.

#### Scenario: Merge default para M4B
- **WHEN** o usuário omite `--output` ou usa o default documentado sob `out/`
- **THEN** o sistema produz um único arquivo `.m4b` com os capítulos em ordem

#### Scenario: Merge para M4B explícito
- **WHEN** o usuário especifica `--output out/livro.m4b` e ffmpeg está disponível
- **THEN** o sistema produz um único arquivo M4B com os capítulos em ordem

#### Scenario: Merge para MP3 sob demanda
- **WHEN** o usuário especifica `--output out/livro.mp3` e há segmentos de áudio válidos
- **THEN** o sistema produz um único arquivo MP3 contendo os capítulos em ordem

### Requirement: Verificar disponibilidade do ffmpeg
Antes do merge, o sistema MUST verificar se `ffmpeg` está disponível no PATH. Se ausente, MUST falhar com mensagem acionável (sem silêncio ou fallback oculto para outro encoder). No ambiente NixOS do projeto, ffmpeg MUST ser fornecido pelo `flake.nix` (devShell).

#### Scenario: ffmpeg ausente
- **WHEN** `ffmpeg` não está no PATH na etapa de merge
- **THEN** o sistema aborta com erro claro instruindo a entrar no devShell/direnv (ou instalar ffmpeg)

### Requirement: Preservar ordem dos capítulos
O arquivo final MUST preservar a ordem dos capítulos/segmentos produzidos pelo pipeline.

#### Scenario: Ordem cronológica
- **WHEN** existem áudios dos capítulos 1, 2 e 3
- **THEN** o arquivo mesclado reproduz 1 → 2 → 3

### Requirement: Artefatos intermediários sob out/
Áudios intermediários de capítulo/segmento usados no merge MUST residir sob o work-dir default `out/` (ex.: `out/chapters/`), não na raiz do repositório nem em diretórios temporários opacos sem path documentado.

#### Scenario: Capítulos gravados em out/chapters
- **WHEN** o pipeline gera áudio por capítulo antes do merge
- **THEN** os arquivos intermediários ficam sob `out/chapters/` (ou subpath equivalente dentro de `--work-dir`)
