## Context

Hoje `OllamaBackend.interpret_chapter` (e `_interpret_unit`) faz uma única chamada LLM por unidade: traduzir, segmentar, descobrir personagens (`story_updates`) e atribuir `speaker_id`/emotion. O speaker QA cobre colapso em protagonista e prosa→personagem, mas **não** colapso de diálogo em `narrator` (`_check_dominance` retorna cedo quando `non_narrator` está vazio).

Evidência (`ch-005` Classroom, `qwen3.6:27b`): `office_lady` / `blond_boy` / `elderly_woman` entram em `story.json` com `voice_profile`, mas a maioria das falas do loiro/senhora/garota vira `narrator`. O elenco existe; a atribuição falha.

Constraints: prompts externos; JSON Pydantic; unit split (`LLM_INTERPRET_MAX_CHARS`); cache por unidade + políticas; resume via `interpret_progress`; voice design lazy após personagens no story; default `qwen3:8b` ainda deve permanecer viável.

## Goals / Non-Goals

**Goals:**

- Separar Pass 1 (cast discovery) de Pass 2 (interpret/diarize).
- Pass 1 cobre o capítulo-fonte completo (ou chunking de cobertura total se o contexto não couber).
- Pass 2 recebe speaker set fechado (`narrator` ∪ falantes do capítulo; mentioned-only fora).
- `narrator` = narração, não fallback de incerteza.
- Reusar `story_state` / `Character` / merge de aliases existentes; participação speaker/mentioned é metadata chapter-local.
- Cache + resume conscientes das duas passagens; bump de política.
- QA de narrator-collapse como rede de segurança; retries só de Pass 2 (sem refresh automático de Pass 1 no MVP).
- Regressão estrutural da classe de falha `ch-005` (não hardcode do capítulo).

**Non-Goals:**

- Trocar LLM default ou TTS.
- Redesign de voice cloning / Parler.
- Hardcode de elenco por livro/capítulo.
- Resolver 100% das ambiguidades de diarização só com heurísticas pós-processamento.
- Pass 1 fazer tradução completa, emoção ou render final de turnos.
- Sampling head+tail do capítulo na Pass 1.
- Refresh automático de Pass 1 após narrator-collapse (adiado pós-MVP).

## Decisions

### D1 — Pass 1 uma vez por capítulo; Pass 2 por unidade

**Escolha:** Discovery no **capítulo inteiro** (texto-fonte completo) quando couber no contexto. Interpretação continua particionada por `InterpretUnit` como hoje.

**Por quê:** Personagens que entram no meio do capítulo (ex. schoolgirl) precisam estar no cast de todas as unidades. Pass 1 emite JSON pequeno — contexto longo é aceitável. Pass 2 permanece a chamada cara e se beneficia do unit split.

**Alternativas:** Pass 1 por unidade (cast inconsistente entre unidades); Pass 2 também no capítulo inteiro (reabre truncamento JSON).

### D2 — Reusar modelo `Character` / merge via `apply_story_updates`

**Escolha:** Saída Pass 1 valida para um schema enxuto (ex. `LLMCastDiscoveryResponse`) cujas identidades sejam compatíveis com `Character` / `StoryUpdates.characters` (id, name, aliases, `voice_profile` opcional). Participação no capítulo (`speaker` / `mentioned`, ou equivalente booleano) vive em **entrada chapter-local** (ex. `ChapterCastEntry`), **não** como campo persistente de `Character`. Merge de identidades no `working_state` **antes** da Pass 2.

**Por quê:** Evita terceira fonte de verdade; speaking status muda por capítulo; voice design e `voice_map` continuam iguais.

**Alternativas:** `role` global em `Character` (incorreto — speaker em A, mentioned em B); estrutura só-capítulo descartável sem merge no story.

### D3 — Speaker set fechado na Pass 2

**Escolha:** Prompt + validação pós-schema: todo `speaker_id`/`speaker_name` resolvido MUST ser `narrator` ou um id classificado como falante no chapter cast (`speaker`, e se o schema MVP incluir `possible_speaker`, também esse). Mentioned-only NÃO entram no speaker set. Speaker fora do conjunto → falha de interpretação (retry), não silent `narrator`.

**Por quê:** Invariante central da change. Reduz o espaço de diarização e evita atribuir fala a quem só é discutido.

**Alternativas:** Soft constraint só no prompt (fraco); speaker set = todo chapter cast incluindo mentioned (mais ruído); permitir `story_updates.characters` na Pass 2 (regride ao single-pass).

### D4 — Personagem genuinamente omitido / narrator-collapse (MVP)

**Escolha:** Não auto-expandir cast e **não** refresh automático de Pass 1. Narrator-collapse QA / speaker-fora-do-set falham a tentativa Pass 2; retries Pass 2 reutilizam o **mesmo** chapter cast fechado + mensagem de QA + instrução de correção. Se esgotar tentativas, aborta a unidade (semântica de falha existente). Refresh Pass 1 / sinal structured missing-speaker fica fora do MVP.

**Por quê:** O bug `ch-005` é atribuição com cast já conhecido. Refresh de discovery adiciona invalidação de cache, fingerprints mudando mid-chapter, unidades stale e loops Pass1↔Pass2.

**Alternativas:** Re-Pass 1 com feedback — útil pós-MVP quando houver evidência clara de discovery incompleta.

### D5 — `voice_profile` e voice design

**Escolha:** Pass 1 MAY emitir `voice_profile` para personagens **novos**. Geração de áudio de voz permanece no pipeline pós-interpret quando `character_id ∉ voice_map`. Pass 2 NÃO dispara voice design. Cache Pass 1/2 NÃO re-gera vozes.

**Por quê:** Dependência real é “personagem existe antes de atribuir fala”, não “voz já clonada”.

### D6 — Escopos conceituais (sem três persistências)

| Escopo | Representação |
|---|---|
| story cast | `StoryState.characters` (+ `voice_map`) — identidade persistente |
| chapter cast | lista em memória após Pass 1: identidade + participation chapter-local |
| speaker set | `{"narrator"} ∪ {ids com participation speaker[/possible_speaker]}` |

Não exigir `chapter_cast.json` persistido no MVP; cache LLM da Pass 1 basta para não redescobrir. Mentioned-only ficam no chapter cast para contexto/identidade, mas fora do speaker set.

### D7 — Cache keys

**Escolha:**

- Pass 1: chave distinta (ex. `cast-{hash}`) incluindo `chapter.id`, hash do texto do capítulo, modelo, `cast_fp` do story, versões de política.
- Pass 2: chave de interpret atual + fingerprint do **chapter speaker set** (além do story cast), para invalidar se Pass 1 mudar.

Bump `LLM_DIARIZATION_POLICY_VERSION` (ex. `v6` → `v7`) para missar caches single-pass.

### D8 — Resume / interpret_progress

**Escolha:** Capítulo só marca progresso após Pass 1 + todas as unidades Pass 2 + merge story/manifest (como hoje, mas including discovery). Mudança de `diarization_policy_version` invalida skip (já existente).

**Por quê:** Evita skip de capítulos interpretados no single-pass antigo após upgrade.

### D9 — Narrator-collapse QA

**Escolha:** Novo invariante (prefixo `speaker QA narrator-collapse`) quando, aproximadamente:

- chapter/unit tem evidência de ≥2 falantes candidatos (speaker set / nomes no texto), **e**
- há volume mínimo de turnos speech-like (`is_speech_turn` / limiar configurável), **e**
- fração alta desses turnos está em `narrator` (threshold dedicado, distinto do dominance de protagonista).

Não depender só de aspas. Reusar `is_speech_turn` e evidências de cast. Em falha: retry Pass 2 com o mesmo cast (D4) — nunca aceitar colapso silenciosamente nem expandir cast.

**Por quê:** Fecha o buraco do `if not non_narrator: return` sem substituir a arquitetura two-pass.

### D10 — Prompts

**Escolha:** Novo arquivo `llm/prompts/discover_cast.md` (Pass 1: quem existe, quem pode falar, aliases; sem diarização por turno). Atualizar `interpret_chapter.md` (Pass 2): lista explícita de IDs permitidos; proibir novos `speaker_id`; reforçar que `narrator` ≠ fallback; manter regras de pt-BR / speech-tags / emoção.

### D11 — Cobertura completa do texto-fonte na Pass 1 (OQ1)

**Escolha:** Pass 1 MUST receber o **capítulo-fonte bruto completo** por padrão. **Proibido** sampling silencioso `head+tail`.

Prioridade:

1. Uma chamada Pass 1 com o capítulo inteiro, se couber no contexto suportado/configurado.
2. Se impossível: **chunking determinístico de cobertura total** (split + merge de casts parciais com a mesma lógica de identidade/aliases). Sem sumarização hierárquica elaborada no MVP.
3. Nunca head+tail.

**Por quê:** Discovery precisa ver falantes que só aparecem no meio/fim e referências resolvidas só com contexto posterior (ex. “unknown girl” → Horikita na unit 3).

### D12 — Participação chapter-local speaker vs mentioned (OQ2)

**Escolha:** Pass 1 classifica participação no capítulo. MVP: enum mínimo `speaker` | `mentioned` (ou `speaks: bool`). Opcional barato: `possible_speaker` incluso no speaker set. **Não** gravar isso como propriedade global de `Character`.

Pass 1 responde “quem existe / quem pode falar / aliases”. Pass 2 responde “qual speaker permitido dono deste turno”.

### D13 — Sem refresh automático de Pass 1 (OQ3)

**Escolha:** Confirmado em D4. Pós-MVP poderá distinguir DIARIZATION FAILURE (retry Pass 2) vs DISCOVERY FAILURE (refresh Pass 1 com sinal missing-speaker) — fora deste change.

## Risks / Trade-offs

- [~2× chamadas LLM] → Pass 1 output curto + cache; Pass 1 1×/capítulo (ou N chunks só se contexto estourar).
- [Pass 1 omite falante] → QA narrator-collapse + retries Pass 2; refresh Pass 1 adiado (D4/D13).
- [Chunked discovery merge errado] → Reusar merge de identidades; testes de merge de casts parciais.
- [Aliases ambíguos (“the girl”)] → Preferir ids do story; aliases locais no chapter cast; testes com Horikita/Suzune.
- [Falsos positivos no narrator-collapse em monólogos] → Exigir evidência multi-speaker + limiares; monólogo sem cast multi-speaker passa.
- [Mentioned classificado como speaker] → Preferir falso positivo `possible_speaker`/`speaker` a excluir falante real; mentioned-only fora do set.
- [Caches legados] → Bump de política + interpret_progress invalidation.
- [Custo wall-clock no Classroom 42 caps] → Aceitável vs vozes erradas; monitorar tempos Pass 1.

## Migration Plan

1. Implementar atrás da política `v7` (ou bump acordado).
2. Work-dirs mid-run: ao retomar com política nova, reinterpretar (progress inválido).
3. Sem migração de `story.json` schema além de personagens adicionais descobertos corretamente; participation permanece chapter-local / não-persistente no Character global.
4. Rollback: reverter política/código; caches `cast-*` ignorados.

## Resolved Questions

| # | Pergunta | Decisão MVP |
|---|---|---|
| OQ1 | Pass 1 sempre no capítulo completo? | Sim; se não couber → chunking de cobertura total; nunca head+tail |
| OQ2 | Distinguir speaker vs mentioned? | Sim; metadata chapter-local; speaker set = narrator + speakers |
| OQ3 | Refresh automático Pass 1 no narrator-collapse? | Não; só retry Pass 2 com o mesmo cast |
