## Context

O pipeline `generate` tem duas fases: Pass A (interpret + voice-design sob demanda) e Pass B (TTS contínuo). Resume de TTS via manifest já existe; Pass A sempre recomeça do primeiro capítulo. O cache LLM inclui `story_state.model_dump()` no hash — no restart o story já populado muda a chave e força novas chamadas Ollama (observado: Cover re-interpretado, elenco 3→6). `OLLAMA_KEEP_ALIVE=-1` no chat é anulado pelo `unload()` após cada capítulo com `last_used_remote`.

Constraints: exclusão mútua VRAM (Ollama / Parler voice-design / Qwen3-TTS); story sequencial; work book-scoped sob `work/<book_id>/`.

## Goals / Non-Goals

**Goals:**

- Restart mid-Pass-A continua do próximo capítulo não concluído, sem re-chamar Ollama nos já feitos.
- Cache LLM hit estável entre restarts quando texto da unidade + modelo + políticas coincidem.
- Manter Ollama residente entre capítulos do Pass A quando não há Voice Design GPU no caminho.
- Continuar unload obrigatório antes de Voice Design (com trabalho) e antes do Pass B TTS.

**Non-Goals:**

- Resume parcial *dentro* de uma unidade LLM (retry mid-HTTP).
- Mudar modelo default ou tamanho de unidade (`LLM_INTERPRET_MAX_CHARS`).
- Manter Ollama carregado durante Voice Design ou TTS.
- Reinterpretar automaticamente capítulos já marcados quando o prompt muda (invalidação via bump de policy version + cache; skip de capítulo é explícito via progresso).

## Decisions

### 1. Progresso de interpretação: set de `chapter_id` em artefato book-scoped

**Escolha:** Persistir `interpreted_chapter_ids: list[str]` (ordenada/única) em `work/<book_id>/interpret_progress.json` (Pydantic pequeno), gravado **atomicamente após** interpret bem-sucedido + merge de manifest + save de story daquele capítulo.

**Alternativas:**
- Inferir só pelo manifest (“há chunks deste chapter_id”) — falha em capítulo interpretado sem diálogos / ou parcial se crash após merge parcial.
- Embutir no `story.json` — mistura narrativa com progresso de pipeline.

**Por quê:** Marcador explícito de “Pass A deste capítulo terminou”; crash mid-capítulo não marca → reinterpreta o capítulo inteiro (unidades ainda podem hit de cache).

### 2. Skip no loop Pass A

**Escolha:** Se `chapter.id` ∈ `interpreted_chapter_ids`, pular `interpret_chapter`, voice-design daquele capítulo, e merge de chunks; log + progress `interpret-skip`.

**Por quê:** Story já contém updates; manifest já contém chunks; evitar re-mutação (Cover inventando personagens extras).

### 3. Capítulos legados (work-dir sem progress file)

**Escolha:** Heurística de migração one-shot: se `interpret_progress.json` ausente e o manifest tem ≥1 chunk com `metadata.chapter_id == chapter.id`, tratar como interpretado **apenas se** o capítulo seguinte na ordem do livro *também* já tem chunks **ou** é o último capítulo com chunks e não há evidência de incompleto. Mais simples e seguro: **bootstrap** — ao carregar, se progress ausente, marcar como interpretados todos os `chapter_id` que aparecem no manifest **exceto o último chapter_id presente** (pode estar parcial). O último é re-interpretado (cache pode ajudar).

**Por quê:** Classroom atual tem ch-001…ch-005 no manifest; no restart, skip 001–004, refaz 005 (parcial possível). Aceitável.

### 4. Chave de cache LLM sem dump completo de story

**Escolha:** `user_payload` enviado ao modelo **continua** incluindo `story_state` completo (qualidade de diarização). A **chave de cache** passa a usar: `model`, `chapter.id`, `unit.index`, `unit.text_hash`, `adaptation_policy_id`, e fingerprint estável `characters_fp = sha256(sorted character ids + aliases canônicos)` — **não** o JSON indentado inteiro do story (voice_map/perfis mudam e quebravam hits).

**Bump:** incrementar `LLM_DIARIZATION_POLICY_VERSION` (ou fragmento de cache) para invalidar caches antigos com chave antiga.

**Alternativa rejeitada:** cache key = só texto da unidade — demais cego a elenco conhecido; fingerprint de ids é o meio-termo.

### 5. Unload Ollama condicional no Pass A

**Escolha:**

```
após interpret_chapter:
  se last_used_remote E chapter precisa voice-design GPU (missing voices):
      unload → wait → voice-design
  senão:
      NÃO unload  # keep_alive=-1 mantém residente
antes do Pass B TTS:
  unload se modelo pode estar residente
```

Entre capítulos sem personagens novos, o modelo fica forever até idle default — com `-1` no chat, forever até unload explícito.

**Alternativa rejeitada:** unload sempre (status quo) — simples mas ~15s+ reload × N capítulos.

### 6. Invalidação de interpret progress

**Escolha:** Se `LLM_ADAPTATION_POLICY_VERSION` / `LLM_DIARIZATION_POLICY_VERSION` / modelo CLI diferirem de metadados gravados no progress file, **ignorar** progress (reinterpretar tudo) ou exigir flag futura `--force-reinterpret`. Gravar `model` + policy ids no progress file.

## Risks / Trade-offs

- **[Risk] Skip com story/manifest dessincronizados** → Mitigation: gravar progress só após story save + manifest merge; testes de ordem.
- **[Risk] Bootstrap legado marca capítulo parcial como done** → Mitigation: excluir o último `chapter_id` do manifest do bootstrap.
- **[Risk] Cache hit com elenco “errado”** (mesmo ids, aliases diferentes sem mudança de fp) → Mitigation: incluir aliases ordenados no fingerprint; bump policy quando regras de speaker mudarem.
- **[Risk] Ollama residente impede Voice Design se esquecer unload** → Mitigation: caminho voice-design sempre unload+wait antes do worker; testes de handoff.
- **[Trade-off] Capítulo interrompido no meio é refeito inteiro** → Aceitável; unidades cacheadas aceleram.

## Migration Plan

1. Deploy da change; work-dirs novos gravam `interpret_progress.json`.
2. Work-dirs antigos: bootstrap na primeira execução pós-change.
3. Caches LLM antigos miss (nova chave / policy bump); sem delete obrigatório.
4. Rollback: remover leitura do progress (sempre reinterpretar) — seguro, só mais lento.

## Open Questions

- Expor `--force-reinterpret` / `--from-chapter` na CLI nesta change ou depois? (default: não bloquear; MAY adicionar se trivial)
- Persistência dentro de `story.json` vs arquivo dedicado — **decidido: arquivo dedicado**.
