## Context

O pipeline atual faz `interpret_chapter` → `dialogues[].text` → TTS. O prompt de interpretação não define idioma de saída; em PDFs em inglês (smoke atual) o áudio sai em inglês. O handoff VRAM (release TTS → interpret → unload LLM → load TTS) já está estável: qualquer solução deve caber **na mesma** chamada de interpretação, sem segunda passagem LLM.

## Goals / Non-Goals

**Goals:**

- Todo `dialogues[].text` consumido pelo TTS em **português brasileiro adaptado** (natural, idiomático), a partir de capítulo em qualquer idioma.
- Adaptação, não tradução literal: preservar sentido, emoção, intenção e ritmo adequados à narração/fala em PT-BR.
- Invalidar caches LLM antigos quando a política de adaptação mudar.
- Manter o contrato JSON (`LLMChapterResponse`) e o fluxo VRAM inalterados.

**Non-Goals:**

- Flag CLI `--lang` / multi-idioma de saída.
- Passo separado de tradução ou segundo unload/load LLM.
- Detecção heurística pós-hoc de “ainda está em inglês” com retry automático (MVP confia no prompt + modelo).
- Traduzir IDs estáveis de personagem ou reescrever `story_updates` além do necessário.
- Mudar o backend TTS ou emoções.

## Decisions

### 1. Adaptação na mesma interpretação (não passo extra)

**Escolha:** enriquecer `interpret_chapter.md` com regras de localização PT-BR; o texto falável já nasce adaptado.

**Alternativas:** (B) segunda chamada “traduzir/adaptar” antes do unload; (C) serviço externo de MT.  
**Por quê:** zero custo VRAM/tempo extra; alinhado ao handoff atual; o LLM já segmenta e escolhe emoção — é o lugar natural para localizar.

### 2. Adaptação ≠ tradução literal

**Escolha:** o prompt instrui a **reescrever** para soar natural em PT-BR (expressões, ordem, registro), sem calque. Manter nomes próprios quando forem identidades (Alice, Bob, topônimos conhecidos), salvo quando houver equivalente usual em PT-BR narrativo.

**Por quê:** pedido explícito do produto; áudio literal em PT calçado soa robótico no TTS.

### 3. Capítulo já em PT-BR

**Escolha:** “garantir PT-BR natural” — se o original já está bem em PT-BR, pode manter/ajustar levemente; não forçar reescrita agressiva.

**Por quê:** evita drift desnecessário e alucinação de sinônimos.

### 4. Cache: incluir versão de política de idioma

**Escolha:** incluir um identificador estável (ex.: `output_locale=pt-BR` + `adaptation_policy=v1`, ou hash/versão do prompt de sistema) na chave de cache de `OllamaBackend`, além de `model` + `chapter.id` + `user_payload`.

**Alternativas:** só apagar `out/cache/` manualmente; incluir o texto inteiro do prompt no hash.  
**Por quê:** a chave atual **ignora** o system prompt — mudar só o `.md` reutilizaria JSON em inglês. Uma constante versionada é previsível e barata; hash do arquivo de prompt também é aceitável se documentado.

### 5. Sem validação automática de idioma no código

**Escolha:** não adicionar detector de idioma no Pydantic neste change.

**Por quê:** falsos positivos/negativos com nomes próprios e termos estrangeiros no meio de PT-BR; custo baixo vs. benefício no MVP. Smoke manual / inspeção do cache JSON bastam para validar.

## Risks / Trade-offs

- **[Modelo ignora a regra e devolve inglês]** → Mitigação: regras fortes e exemplos no prompt; smoke com PDF EN; se recorrente, change futura com retry orientado.
- **[Adaptação inventa conteúdo]** → Mitigação: prompt exige fidelidade ao sentido do capítulo; não inventar falas/eventos.
- **[Caches antigos]** → Mitigação: nova chave; caches órfãos podem ser ignorados ou limpos no smoke.
- **[Nomes / termos de fantasia]** → Mitigação: preservar nomes próprios; adaptar só o restante.
- **[Latência/token]** → Mitigação: mesma chamada; texto PT pode ser um pouco mais longo, aceitável.

## Migration Plan

1. Atualizar prompt + chave de cache.
2. Rodar testes unitários de LLM/prompt/cache.
3. Smoke com PDF em inglês: inspecionar `out/cache/llm-*.json` (textos em PT-BR) e áudio.
4. Rollback: reverter prompt e constante de versão de cache (caches novos ficam órfãos, inofensivos).

## Open Questions

- Nenhum bloqueante: PT-BR fixo; adaptação na interpret; sem detector de idioma no MVP.
