## 1. Prompt PT-BR adaptado

- [x] 1.1 Atualizar `interpret_chapter.md` com regras explícitas: todo `dialogues[].text` em PT-BR adaptado (não literal), fidelidade ao sentido/emoção, nomes próprios estáveis, capítulo já em PT-BR sem reescrita agressiva
- [x] 1.2 Revisar o prompt para manter o contrato JSON existente (speakers, emotion enum, story_updates) sem mudar o schema Pydantic

## 2. Cache e política de adaptação

- [x] 2.1 Introduzir identificador estável de política (ex.: `pt-BR` + versão) e incluí-lo na chave de cache de `OllamaBackend`
- [x] 2.2 Garantir que mudança de política gera cache miss frente a entradas antigas; mesma política continua podendo hit

## 3. Testes

- [x] 3.1 Testar que o prompt carregado contém a política de adaptação PT-BR
- [x] 3.2 Testar invalidação de cache quando a política muda (e hit quando permanece igual)
- [x] 3.3 Ajustar mocks/fixtures de interpretação se assumirem texto de saída no idioma de origem

## 4. Verificação

- [x] 4.1 Rodar testes unitários relevantes (LLM/cache/prompt)
- [x] 4.2 Smoke opcional: PDF em inglês → inspecionar `dialogues[].text` em PT-BR no cache/JSON e áudio coerente
