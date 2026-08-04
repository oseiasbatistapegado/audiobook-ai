## Context

O pipeline já tem speaker QA (narration / attribution / dominance) e repair de prosa→`narrator`. Isso cobre **quem** fala, não **o que** o TTS lê. Em `ch-004` do Classroom, turnos como `"Prova?, perguntou ela."` e `"…, disse ela."` passam no QA (pronome; speaker alinhado) e contaminam a voz do personagem.

Decisão de produto (opção B): **descartar** a tag de atribuição — a voz castada já identifica o falante. Não criar turno `narrator` só para “perguntou ela”.

## Goals / Non-Goals

**Goals:**

- Texto falado de personagem sem speech-tags (`disse`/`perguntou`/`respondeu`/… + `ela`/`ele`/nome).
- Prompt, repair determinístico e QA alinhados (mesma estratégia do speaker QA atual).
- Cache miss via bump de `LLM_DIARIZATION_POLICY_VERSION` (hoje `v5` → `v6`).
- Fixture de regressão para os casos `disse ela` / `perguntou ela`.

**Non-Goals:**

- Manter tags como turnos de narrador (opção A).
- Reescrever prosa narrativa que usa “disse que” / citação histórica (ex. intro do volume).
- Avaliar qualidade PT-BR neste gate.
- Reinterpretar automaticamente workdirs já gerados além do cache miss natural.

## Decisions

### 1. Strip, não split

- **Escolha:** remover o sufixo/trecho de atribuição do `text`; manter um único turno com o mesmo speaker/emotion.
- **Alternativa:** split em fala + narrador — rejeitada (opção A).
- **Rationale:** voz distinta torna a tag redundante e evita TTS lendo meta-texto.

### 2. Escopo do padrão

Aplicar só a turnos **não-narrator** (fala de personagem), tipicamente após fechamento de aspas ou como sufixo colado:

- Verbos PT (+ EN comuns): `disse`, `perguntou`, `respondeu`, `falou`, `gritou`, `sussurrou`, `retrucou`, `said`, `asked`, `replied`, …
- Alvo: `ela` / `ele` / nome próprio capitalizado / 1ª pessoa de atribuição tipo `perguntei`/`respondi` quando colado **fora** da fala (tag narrativa, não o conteúdo da fala).

Não stripar narrador: evita falso positivo em “um pensador disse que…”.

### 3. Ordem no backend

```
parse/sanitize → Pydantic → repair_narration_speakers
  → check_explicit_attribution (pré-strip; preserva sinal nome≠speaker)
  → strip_speech_attribution_tags → check_speaker_diarization
```

O QA completo (pós-strip) cobre narration, attribution residual, speech-tag residual e dominance. A atribuição pré-strip evita perder mismatches quando a tag ainda está colada. O invariante `speaker QA speech-tag` é rede de segurança se o strip falhar.

### 4. Prompt

Complementar (não substituir) as regras de speaker: `dialogues[].text` de personagem MUST conter **apenas** as palavras faladas; MUST NOT incluir tags `disse/perguntou/… ela/ele/Nome`. Atribuição no source informa o `speaker_id`, não o texto lido.

### 5. Relação com invariante de atribuição existente

O checker nome≠speaker permanece. Após o strip, tags alinhadas ao speaker desaparecem do texto; o novo invariante cobre o caso que o antigo **deixa passar** (tag residual em turno de personagem, inclusive pronomes).

### 6. Política de cache

Bump `LLM_DIARIZATION_POLICY_VERSION` para `v6` para forçar re-interpretação.

## Risks / Trade-offs

- **[Risk] Falso positivo no strip** (corta fala legítima que termina com “disse ela” como diálogo) → Mitigation: ancorar em padrão de tag pós-aspas / vírgula + verbo de fala + pronome/nome curto; testes com fixture real e contraexemplos narrativos.
- **[Risk] Falso negativo** (formas raras: “— perguntou ela, secamente”) → Mitigation: QA rejeita residual; retry + ampliar regex se necessário.
- **[Risk] Perda de nuance literária** ao descartar tags → Aceito pela opção B; voz castada substitui a função.
- **[Trade-off] Regex vs LLM-only** → Regex + QA é determinístico e barato; prompt reduz incidência.

## Migration Plan

1. Implementar strip + QA + prompt + bump `v6`.
2. Rodadas novas fazem cache miss e reinterpretam.
3. Workdirs antigos: re-rodar interpret/`generate` (ou limpar cache LLM) para limpar chunks já materializados no manifesto.
4. Rollback: reverter versão de política e código; caches `v6` não colidem com `v5`.

## Open Questions

- Nenhuma bloqueante: opção B confirmada; lista de verbos pode expandir durante implementação se fixtures mostrarem lacunas.
