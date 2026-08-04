## Context

`harden-llm-chapter-interpretation` adicionou split, retries e um QA de **colapso global** (quoted_turns ≥ 6 ∧ dominance ≥ 0.85 ∧ evidence ≥ 2). Em produção no Classroom, `ch-004` passou com dominance ~0.56 ainda errado: prosa de 1ª pessoa em `kiyotaka_ayanokoji` e pelo menos uma fala da Horikita no POV. Baixar o threshold não resolve erros locais. A run atual foi interrompida com manifesto `pending` e **zero áudio** — correto não cristalizar em TTS.

## Goals / Non-Goals

**Goals:**
- Rejeitar turnos sem fala explícita atribuídos a personagem ≠ `narrator`.
- Rejeitar falas cuja atribuição explícita no texto do turno (ou âncora local) contradiz o `speaker_id`/`speaker_name`.
- Manter o detector de dominance como proteção anti-colapso.
- Erros de QA nomeados por invariante; bump de política de cache.
- Fixture `ch-004` obrigatória.

**Non-Goals:**
- Gate de qualidade/adaptação PT-BR (change separada).
- Baixar `LLM_SPEAKER_QA_DOMINANCE_THRESHOLD` como mitigação principal.
- Correção automática de speakers (só reject + retry).
- Alias vocal `narrator` → POV.
- Upgrade de modelo.

## Decisions

### D1 — Três invariantes, OR lógico
A unidade falha o QA se **qualquer** invariante falhar:

1. **Narration:** se o turno NÃO é fala explícita (`is_quoted_turn` / travessão de diálogo) → speaker MUST ser `narrator` (ids/nomes equivalentes: `narrator`, `narrador`).
2. **Explicit attribution:** se o texto do turno (ou sufixo/prefixo imediato no mesmo `dialogues[].text`) casa com padrões do tipo `“…” perguntou X` / `X respondeu: “…”` / `disse X` ancorado à fala → o speaker resolvido MUST ser X (via `story_state` id/nome/alias).
3. **Dominance (existente):** mantém a regra AND atual com defaults 6 / 0.85 / evidence≥2.

**Não** baixar T=0.85: o `ch-004` passa com 0.56 e ainda está errado.

### D2 — Escopo da atribuição explícita
Fase 1: padrões no **próprio** `dialogues[].text` (comum quando o LLM cola “perguntou Horikita” no mesmo item). Resolver X contra `story_state`; se X não resolve a personagem conhecido, NÃO falhar só por isso (evita falso positivo em nomes comuns). Se resolve e diverge do speaker do turno → FAIL.

### D3 — Taxonomia de erro (sem misturar PT-BR)
Mensagens MUST prefixar a invariante, ex.:
- `speaker QA narration: ...`
- `speaker QA attribution: ...`
- `speaker QA dominance: ...`

Qualidade PT-BR MUST NÃO entrar neste checker.

### D4 — Cache
Bump `LLM_DIARIZATION_POLICY_VERSION` → `v2` (ou `v1`→`v2` se ainda `v1`).

### D5 — Regressão
- Manter fixture `ch-011` (dominance).
- Adicionar fixture `ch-004` que falha em **narration** e/ou **attribution** mesmo com dominance < 0.85.

## Risks / Trade-offs

- [Falso positivo: monólogo POV sem aspas tratado como narração] → Correto pela semântica acordada (prosa → narrator); fala do POV MUST vir entre aspas.
- [Falso positivo: “Horikita” em prosa narrativa] → Invariante 2 só aplica quando o padrão ancora uma fala explícita no mesmo turno.
- [Mais retries / abortos] → Aceitável vs áudio errado; 3 tentativas já existem.
- [Manifesto parcial atual] → Limpar antes de re-interpret; não rodar TTS.

## Migration Plan

1. Implementar + bump política `v2`.
2. Apagar manifesto/cache LLM da run Classroom parcial (ou work-dir limpo).
3. Re-rodar `generate` só após o gate novo.
4. Rollback: reverter change + política.

## Open Questions

Nenhuma — decisões fechadas pelo usuário nesta thread.
