## Purpose

Extrair texto de PDFs via PyMuPDF e segmentar o livro em capítulos tipados (`Book` / `Chapter`).

## Requirements

### Requirement: Extrair texto de PDF via PyMuPDF
O sistema SHALL extrair texto de arquivos PDF usando PyMuPDF e SHALL retornar um modelo Pydantic tipado (ex.: páginas/texto agregável), nunca um `dict` arbitrário. PDFs sem texto extraível MUST falhar com erro claro (OCR está fora de escopo).

#### Scenario: PDF com texto selecionável
- **WHEN** o usuário fornece um PDF com texto embutido
- **THEN** o extrator retorna o texto completo das páginas em ordem

#### Scenario: PDF sem texto extraível
- **WHEN** o PDF não contém texto selecionável (ex.: apenas imagens)
- **THEN** o sistema aborta com erro explícito indicando ausência de texto extraível

### Requirement: Segmentar o livro em capítulos
O sistema SHALL dividir o texto extraído em uma lista de capítulos (`Book` com `Chapter` id, title, text). Quando um TOC/bookmarks útil existir, o parser MUST usá-lo. Caso contrário, MUST aplicar heurísticas simples (ex.: padrões "Capítulo N" / "Chapter N") ou um fallback documentado (blocos por páginas).

#### Scenario: PDF com TOC utilizável
- **WHEN** o PDF possui bookmarks/TOC que mapeiam para offsets de página
- **THEN** o parser produz um capítulo por entrada relevante do TOC

#### Scenario: PDF sem TOC
- **WHEN** o PDF não possui TOC utilizável
- **THEN** o parser aplica heurísticas de headings ou fallback e ainda assim produz uma ou mais `Chapter`

#### Scenario: Livro tratado como capítulo único
- **WHEN** nenhuma fronteira de capítulo é detectada
- **THEN** o parser retorna um único capítulo contendo todo o texto
