## ADDED Requirements

### Requirement: Smoke E2E reproduzível com sample PDF
O repositório SHALL incluir `samples/sample.pdf` (PDF curto com texto selecionável) e documentação em `docs/SMOKE.md` descrevendo instalação TTS, configuração Ollama, execução e artefato de saída esperado. Após a instalação inicial documentada, o comando canônico de smoke MUST produzir um M4B sem exigir servidor TTS externo nem comandos manuais além do generate.

#### Scenario: Comando canônico de smoke
- **WHEN** o usuário segue `docs/SMOKE.md` e executa `audiobook-ai generate samples/sample.pdf --output out/sample.m4b` com deps e GPU/Ollama conforme pré-requisitos
- **THEN** o sistema cria `out/sample.m4b` e encerra com código de sucesso

#### Scenario: Documentação cobre 1ª e 2ª execução de pesos
- **WHEN** o usuário lê `docs/SMOKE.md`
- **THEN** o documento descreve a primeira execução (download/cache de pesos) e a segunda (cache hit sem re-download completo)

### Requirement: Documentação de bootstrap TTS
O README (ou SMOKE) MUST documentar a sequência mínima para tornar `import torch` e `import fish_speech` funcionais no ambiente do projeto (extra `tts-fish` + install do pacote fish-speech pinado).

#### Scenario: Validação de import documentada
- **WHEN** o usuário conclui os passos de install TTS documentados
- **THEN** `python -c "import torch; import fish_speech"` sucede no interpretador do projeto
