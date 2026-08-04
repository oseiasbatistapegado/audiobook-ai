## Why

O QA de diarização atual só rejeita colapso global de speakers (dominance ≥ 0.85). Capítulos como `ch-004` passam com ratio ~0.56 ainda atribuindo prosa de 1ª pessoa ao POV e falas trocadas — erros locais que o gate não vê. Precisamos de invariantes determinísticos por turno/atribuição explícita, sem misturar qualidade PT-BR no mesmo gate, antes de sintetizar áudio sobre manifesto incorreto.

## What Changes

- Adicionar invariante **narração**: turnos sem fala explícita (aspas/travessão de diálogo) MUST resolver para `narrator`, inclusive em 1ª pessoa.
- Adicionar invariante **atribuição explícita**: padrões locais (“…” perguntou Horikita / Horikita respondeu: “…”) MUST exigir o `speaker_id`/`speaker_name` correspondente (resolvido via `story_state`).
- Manter o detector de **dominance/colapso global** como rede de segurança (não baixar o threshold como “solução”).
- Mensagens de QA MUST identificar qual invariante falhou (para retry acionável e diagnóstico).
- Bump de `LLM_DIARIZATION_POLICY_VERSION` para invalidar caches que passaram só no gate de colapso.
- **Fora de escopo:** gate de qualidade/adaptação PT-BR (problema separado).
- Fixture de regressão obrigatória derivada do `ch-004` (prosa→POV + fala Horikita no Ayanokoji).

## Capabilities

### New Capabilities
<!-- nenhuma — estende o gate existente -->

### Modified Capabilities
- `llm-interpretation`: Expandir o gate de QA de diarização com invariantes locais (narração + atribuição explícita), manter dominance, separar PT-BR do gate, versionar política de cache.

## Impact

- Código: `llm/speaker_qa.py`, testes/fixtures (`ch-004`, `ch-011`), bump de política em `config.py`; retries já existentes consomem as novas falhas.
- Runs em andamento com manifesto parcial errado: NÃO iniciar TTS; limpar manifesto/cache LLM do livro e re-interpretar após o deploy.
- Sem mudança de modelo default (`qwen3:8b`); sem mudança no TTS.
