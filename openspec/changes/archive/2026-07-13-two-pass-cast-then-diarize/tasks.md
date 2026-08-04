## 1. Schema, config e política

- [x] 1.1 Adicionar modelos Pydantic Pass 1: resposta de discovery + entrada chapter-local (identidade + `participation`/`speaks`; sem campo global em `Character`)
- [x] 1.2 Bump `LLM_DIARIZATION_POLICY_VERSION` e defaults/config para limiares de narrator-collapse QA e, se necessário, limite de contexto Pass 1
- [x] 1.3 Helper de speaker set: `{"narrator"} ∪ {ids com participation speaker[/possible_speaker]}` (exclui mentioned-only)

## 2. Pass 1 — cast discovery

- [x] 2.1 Criar prompt externo `llm/prompts/discover_cast.md` (quem existe / quem fala vs mentioned / aliases; sem diarização por turno)
- [x] 2.2 Implementar Pass 1 com capítulo-fonte completo + story_state; retries JSON/schema
- [x] 2.3 Se o capítulo exceder o contexto Pass 1: chunking determinístico de cobertura total + merge de casts (nunca head+tail)
- [x] 2.4 Cache distinto Pass 1 (`cast-*`) com chave: chapter id, text hash, model, story cast fp, políticas
- [x] 2.5 Merge de identidades no `working_state` via `apply_story_updates` / aliases antes da Pass 2 (sem voice design); conservar participation só em memória/chapter cast

## 3. Pass 2 — interpret com cast fechado

- [x] 3.1 Atualizar `interpret_chapter.md` / montagem de prompt: lista só de falantes + narrator; `narrator` ≠ fallback; proibir novos `speaker_id`
- [x] 3.2 Wire `interpret_chapter`: Pass 1 → por unidade Pass 2 com speaker set; incluir fingerprint do speaker set na cache key Pass 2
- [x] 3.3 Validar pós-schema que todo speaker resolve para o speaker set; fora do conjunto → falha/retry
- [x] 3.4 Garantir que Pass 2 não introduza falantes novos via `story_updates.characters` como substituto da Pass 1

## 4. Speaker QA — narrator-collapse

- [x] 4.1 Implementar invariante `speaker QA narrator-collapse` (multi-speaker evidence + speech-like volume + fração alta em `narrator`)
- [x] 4.2 Em falha: retry só Pass 2 com o mesmo cast + erro QA; NÃO refresh Pass 1; retries esgotados → abort da unidade
- [x] 4.3 Integrar no gate existente sem quebrar narration / attribution / speech-tag / dominance
- [x] 4.4 Adicionar fixture de regressão derivada de `ch-005` (ônibus: blond_boy/elderly/schoolgirl → narrator) e testes

## 5. Resume, vozes e regressão

- [x] 5.1 Confirmar que `interpret_progress` só marca capítulo após Pass 1 + todas unidades Pass 2; política nova invalida skip single-pass
- [x] 5.2 Verificar que voice design permanece lazy pós-personagem no story e não duplica geração por Pass 1
- [x] 5.3 Testes: cache Pass 1 hit/miss; mentioned fora do set; chunk-merge de discovery; speaker fora do set; fluxo two-pass mínimo
- [x] 5.4 Rodar suite relevante (`test_llm`, `test_speaker_qa`, `test_interpret_progress`, etc.) e ajustar docs curtos se necessário (SMOKE/README só se já documentam o fluxo interpret)
