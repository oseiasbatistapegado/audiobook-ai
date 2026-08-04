## Context

O pipeline faz Pass A (interpretar todos os capítulos → manifesto pending) e Pass B (TTS contínuo). A interpretação atual (`OllamaBackend.interpret_chapter`) valida só JSON + Pydantic, com **um** retry. Com `qwen3:8b`, respostas schema-válidas frequentemente colapsam falas multi-personagem no protagonista/POV, e capítulos longos geram JSON ~100KB truncado/inválido que aborta o livro inteiro. Constraint explícita desta change: **continuar com default `qwen3:8b`** — qualidade via prompt + gates + partição, não via modelo maior.

## Goals / Non-Goals

**Goals:**
- Atribuição de speaker utilizável em capítulos com diálogo multi-personagem no `qwen3:8b`.
- Capítulos longos interpretáveis sem crash por JSON truncado (via unidades menores + retries melhores).
- Invalidar caches de interpretação gerados sob a política antiga.
- Manter o contrato `LLMChapterResponse` e o fluxo Pass A → Pass B.

**Non-Goals:**
- Trocar o default de modelo para 35B (ou qualquer upgrade obrigatório).
- Diarização perfeita / revisão humana / UI de correção de speakers.
- Segundo passo LLM só para “fix speakers” (pode existir retry com o **mesmo** prompt/contrato, não um pipeline paralelo de tradução/diarização).
- Mudar chunking TTS (`TTS_MAX_CHUNK_CHARS`) ou o worker Qwen3-TTS.
- Soft-skip silencioso de capítulos com falha permanente (ainda aborta com erro contextual após esgotar retries da unidade).
- Implementar alias vocal `narrator` → voz do POV no VoiceRegistry (permitido no futuro/config; fora desta change).

## Decisions

### D1 — Prompt endurecido para diarização (mesmo modelo)
**Escolha:** Expandir `interpret_chapter.md` com regras normativas:
- **Narração** (incluindo prosa em 1ª pessoa) → `speaker_id`/`speaker_name` = `narrator`.
- **Fala explícita do POV/protagonista** → `character_id` do protagonista (não `narrator`).
- Cada turno com fala entre aspas/travessão → **um** speaker; não misturar falas de personagens diferentes no mesmo `text`.
- Preferir ids existentes do `story_state`; personagens novos MUST aparecer em `story_updates.characters`.
- Attribution clues no texto (“X disse”, “respondeu Y”) MUST bater com o speaker do turno.

**Semântica `speaker_id` ≠ `voice_id`:** papel narrativo e identidade vocal são ortogonais. `speaker_id=narrator` NÃO obriga voz fisicamente distinta do POV. O VoiceRegistry MAY, no futuro ou por configuração, mapear `narrator` → a mesma `voice_id` do protagonista (ex. `k-ayankoji`) sem corromper os dados. Esta change NÃO implementa esse alias de voz; só preserva a separação semântica para não repetir o bug “POV ⇒ Ayanokoji falou tudo”.

**Alternativas:** Só modelo maior — rejeitada (requisito do usuário). Atribuir prosa de 1ª pessoa ao protagonista — rejeitada: colapsa função narrativa com speaker de diálogo. Dois prompts (segmentar vs atribuir) — adiada; aumenta latência/VRAM churn; retry + QA deve bastar no 8B com unidades menores.

### D2 — Gate de QA semântica pós-schema
**Escolha:** Após `LLMChapterResponse` válido, rodar um checker determinístico (sem LLM) que pode rejeitar a resposta e alimentar o retry com mensagem específica (ex.: “quoted turns collapsed to a single character_id while chapter names multiple speakers”).

**Defaults fechados:**
- `LLM_SPEAKER_QA_MIN_QUOTED_TURNS = 6`
- `LLM_SPEAKER_QA_DOMINANCE_THRESHOLD = 0.85`

O QA **FAIL** somente quando as três condições valem ao mesmo tempo:
1. `quoted_turns >= LLM_SPEAKER_QA_MIN_QUOTED_TURNS`
2. `dominant_speaker_ratio >= LLM_SPEAKER_QA_DOMINANCE_THRESHOLD` (razão do speaker não-`narrator` mais frequente entre turnos falados)
3. `evidence_of_multiple_speakers >= 2`

`evidence_of_multiple_speakers` MUST contar evidências distintas além do speaker dominante, incluindo:
- personagens conhecidos no `story_state` (nome/aliases) mencionados no texto da unidade;
- atribuições explícitas locais (ex. “disse Sudou”, “respondeu Horikita”).

**Regressão obrigatória:** o caso `ch-011` (trecho Sudou/Ike/Yamauchi colapsado em `k-ayankoji`) MUST ser fixture de regressão do checker.

**Alternativas:** Aceitar tudo e corrigir no TTS — inviável. Exigir lista explícita de speakers do LLM e diff vs texto — mais frágil no 8B. QA só em CI — não protege `generate`.

### D3 — Particionar capítulos longos em unidades de interpretação
**Escolha:** Antes de chamar Ollama, se `len(chapter.text) > LLM_INTERPRET_MAX_CHARS` (**default fechado: 6000**, não 8000 — unidades menores atacam truncamento e perda de precisão de speakers), dividir por fronteiras de parágrafo (depois sentença) em unidades ≤ limiar, preservar ordem, interpretar sequencialmente.

- Cada unidade recebe `story_state` **atualizado** pelas unidades anteriores do mesmo capítulo (personagens novos ficam visíveis).
- Concatenar `dialogues` na ordem das unidades.
- Agregar `story_updates` (characters/aliases) de forma determinística (última voice_profile vence por id; aliases união).
- Cache: chave por **unidade** (capítulo + índice/hash do trecho + política), não só por capítulo inteiro — evita reprocessar unidades ok quando uma falha.

**Alternativas:** Aumentar `num_ctx`/`num_predict` só — não resolve colapso de speaker e ainda falha em outputs enormes. Pedir ao LLM “resuma menos turnos” — perde fidelidade para TTS. Soft-fail capítulo — deixa buracos no audiolivro.

### D4 — Retries enriquecidos (JSON / schema / QA)
**Escolha:** Substituir “1 retry” por até `LLM_INTERPRET_MAX_ATTEMPTS` (**default fechado: 3**) no **mesmo** fluxo de chat, com erro específico (JSONDecodeError, ValidationError, ou QA). Opcional: reparo leve pré-parse (trailing commas óbvios) **antes** de contar como falha de JSON — não inventar conteúdo.

**Alternativas:** Retry infinito — risco de loop/custo. Modelo maior no retry — fora de escopo.

### D5 — Versionar política de cache
**Escolha:** Estender `_adaptation_policy_id()` (ou equivalente) com versão de política de diarização/QA/split (ex. `diarization_policy=v2`), de modo que caches do 8B com speakers colapsados não façam hit após o deploy.

### D6 — Onde vive a orquestração
**Escolha:** Split + aggregate no backend LLM ou em helper chamado pelo pipeline **antes**/ao redor de `interpret_chapter`, mantendo a API pública `interpret_chapter(chapter, story)` capaz de opaque-mente particionar. Preferência: lógica de split em módulo dedicado (`llm/units.py` ou similar) usado pelo backend, para testes unitários sem pipeline completo.

## Risks / Trade-offs

- [QA com falso positivo em monólogo] → Exigir `quoted_turns` mínimo + menção a múltiplos nomes; limiares em config; log claro no retry.
- [QA com falso negativo (ainda colapsa)] → Prompt + unidades menores reduzem carga; limiares podem apertar depois; evidência no `ch-011` como fixture de regressão.
- [Mais chamadas Ollama / Pass A mais lenta] → Aceitável vs crash; split só acima do limiar; cache por unidade.
- [Fronteira de split corta diálogo no meio] → Preferir parágrafos; se parágrafo > limiar, split por sentença; documentar que unidade pode começar mid-scene.
- [story_updates inconsistentes entre unidades] → Aggregate determinístico; passar state acumulado.
- [Manifesto atual já tem speakers errados] → Cache miss força re-interpret; usuário pode precisar apagar manifesto/chunks da run ruim ou regenerar — documentar no Migration.

## Migration Plan

1. Deploy código + bump de política de cache.
2. Runs novas: miss em caches antigos; interpret refeito com split/QA.
3. Runs em andamento com manifesto parcial ruim: orientações no README/SMOKE — invalidar cache LLM do livro e/ou remover manifesto/story parcial afetado antes de re-rodar `generate` (sem migração automática destrutiva).
4. Rollback: reverter change; política antiga volta a hit nos caches antigos se ainda existirem.

## Open Questions

Nenhuma — fechadas:

| Decisão | Valor |
|---|---|
| `LLM_INTERPRET_MAX_CHARS` | `6000` |
| `LLM_INTERPRET_MAX_ATTEMPTS` | `3` |
| `LLM_SPEAKER_QA_MIN_QUOTED_TURNS` | `6` |
| `LLM_SPEAKER_QA_DOMINANCE_THRESHOLD` | `0.85` |
| Prosa / 1ª pessoa | `narrator` |
| Fala explícita do POV | `character_id` do protagonista |
| `speaker_id` vs `voice_id` | Ortogonais; alias vocal narrator→POV é futuro/config, fora do escopo de implementação desta change |
| Fixture | `ch-011` obrigatória para regressão do QA |
