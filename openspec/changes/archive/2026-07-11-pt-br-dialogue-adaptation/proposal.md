## Why

O pipeline de audiolivro precisa falar em português brasileiro: PDFs podem estar em qualquer idioma, e a interpretação atual preserva o idioma de origem no `dialogues[].text` enviado ao TTS. Uma tradução literal soaria artificial; o texto falado precisa ser **adaptado** ao PT-BR natural, mantendo sentido, emoção e ritmo narrativo.

## What Changes

- O estágio de interpretação LLM passa a produzir **todo** `dialogues[].text` em português brasileiro adaptado (localização narrativa, não tradução palavra a palavra).
- O prompt externo de interpretação ganha regras explícitas de adaptação PT-BR (incluindo prosa de narrador e falas).
- A chave de cache LLM passa a invalidar quando a política de idioma/adaptação muda (evita reutilizar caches em inglês ou outro idioma).
- Nomes próprios / IDs de personagem permanecem estáveis quando fizer sentido; o que muda é o texto falável.
- Sem passo LLM extra de tradução: a adaptação ocorre na mesma chamada `interpret_chapter`, antes do unload e do TTS.
- Sem flag `--lang` neste change (PT-BR fixo como idioma de saída do áudio).

## Capabilities

### New Capabilities

- (nenhuma)

### Modified Capabilities

- `llm-interpretation`: exigir que cada `dialogues[].text` seja PT-BR adaptado a partir do capítulo de origem (qualquer idioma), com regras de prompt e invalidação de cache alinhadas a essa política.

## Impact

- Prompt: `src/audiobook_ai/llm/prompts/interpret_chapter.md`
- Backend: `src/audiobook_ai/llm/ollama_backend.py` (chave/versão de cache)
- Specs/testes de interpretação LLM; caches locais existentes em `out/cache/` deixam de ser válidos para a nova política
- Pipeline e TTS inalterados na API: continuam consumindo `dialogue.text` já adaptado
- Sem novas dependências de pacote
