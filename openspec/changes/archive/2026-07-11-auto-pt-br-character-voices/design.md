## Context

O pipeline atual faz `interpret_chapter` → `ensure_voice` (round-robin em `DEFAULT_VOICE_REFERENCE_IDS`) → Fish Speech com `reference_id`. Na prática só `assets/voices/narrator/` existe, e o clipe empacotado é inglês de smoke. IDs `voice_01`…`voice_05` são simbólicos: o backend faz fallback para `narrator`. Texto dos diálogos já é pt-BR (change `pt-br-dialogue-adaptation`); o sotaque segue a referência clonada.

Fish Speech (`ServeTTSRequest`) **não** tem parâmetro `language`/`locale`. A qualidade pt-BR depende de referência pt-BR + texto pt-BR.

Pesquisa de backends (2024–2026) para *character description → voz distinta → referência reutilizável*:

| Abordagem | pt-BR verificável? | Fit MVP |
|-----------|--------------------|---------|
| Banco estático pt-BR + assign determinístico | Sim (se refs forem BR) | **Primário** |
| Fish Speech + N refs empacotadas | Depende da ref | Backbone TTS |
| Piper `pt_BR` / Kokoro BR | Sim (docs oficiais) | Seed do banco |
| Parler-TTS `freds0/...-ptbr` | Sim (card BR) | Pós-MVP / experimental |
| Qwen3-TTS VoiceDesign | Portuguese genérico; relatos de sotaque PT-PT | **Não** como dependência dura |
| CosyVoice Instruct / OpenVoice / MeloTTS | Sem PT nativo | Rejeitado |
| Edge-TTS | pt-BR Neural | Rejeitado (cloud) |

Constraint de hardware: AMD RX 7900 XTX / ROCm já suportado no hot path Fish Speech; o MVP evita segundo modelo GPU no caminho crítico.

## Goals / Non-Goals

**Goals:**

- Personagem novo → perfil vocal semântico (opcional) → identidade vocal pt-BR real e persistente, sem áudio de referência manual por personagem.
- Narrator com voz dedicada pt-BR, nunca compartilhada com personagem.
- Abstração `VoiceGenerator` + registry em disco; Fish Speech só consome refs prontas.
- Determinismo (`seed` estável via hash criptográfico, não `hash()` do Python).
- Testes automatizados + smoke auditivo com ≥3 vozes distintas em pt-BR.

**Non-Goals:**

- GUI / API web / cloud TTS.
- Celebridade / impersonação.
- Voice design livre por texto no MVP (Parler/Qwen ficam como evolução).
- Substituir Fish Speech no hot path.
- Emoção perfeita, SFX, música.
- Validação automática de sotaque por classificador ML no MVP (smoke humano + metadados `language=pt-BR` + proveniência do banco).

## Decisions

### D1 — Estratégia MVP: banco pt-BR + atribuição determinística

**Escolha:** Manter um catálogo de vozes base com `language=pt-BR` (metadata obrigatória), cada uma com `reference.wav` + texto alinhado (`.lab`/`.txt`). O `VoiceGenerator` seleciona (ou materializa no cache) uma voz do banco a partir do `CharacterProfile` / `voice_profile`, sem inventar sotaque.

**Por quê:** É a única abordagem local simples com pt-BR **garantível** (proveniência das refs). Voice design por texto com pt-BR de produção não está maduro o bastante para requisito não-negociável.

**Alternativas rejeitadas:** depender de Qwen VoiceDesign / CosyVoice Instruct / OpenVoice sem evidência pt-BR sólida.

### D2 — Fish Speech permanece o único TTS do livro

**Escolha:** Geração de identidade vocal (one-shot) → persistir ref → Fish Speech clona em todas as falas.

**Por quê:** Já integrado in-process + ModelManager + VRAM handoff. Piper/Kokoro só como fontes potenciais de *seed* offline do banco, não no hot path.

### D3 — Abstração `VoiceGenerator` + `VoiceRegistry`

**Escolha:**

```text
CharacterProfile (+ language=pt-BR)
        ↓
VoiceGenerator.generate_voice(...)
        ↓
GeneratedVoice { voice_id, language, paths, generator, seed }
        ↓
VoiceRegistry.ensure / get  (~/.cache/audiobook-ai/voices/<voice_id>/)
        ↓
voice_map[character_id] = voice_id
        ↓
FishSpeechBackend resolve reference dir
```

Implementação MVP: `BankVoiceGenerator` (seleção no catálogo + cópia/materialização no registry). Interface pronta para backend futuro (ex. Parler) sem mudar o pipeline.

### D4 — Banco inicial: 6 vozes, extensível

**Escolha:** MVP entrega **6** vozes no total: **1 narrator dedicado** + **5 bases de personagem**. Mistura masculino/feminino/idade; cada uma com metadata de licença e `language: pt-BR`.

O tamanho do banco MUST permanecer **extensível** (descoberta via catálogo/filesystem). A lógica de atribuição MUST NÃO hardcodar `5`/`6` como constante de capacidade — novos assets no catálogo entram automaticamente no pool.

Preferência de origem:

1. Clipe curto gerado offline via Piper `pt_BR` e/ou Kokoro BR (`pf_dora`, `pm_alex`, `pm_santa`, …) com frase canônica pt-BR no `.lab`.
2. Gravações licenciadas explicitamente pt-BR.

**Validação (MVP):** metadados `language=pt-BR` explícitos + proveniência da fonte + texto de referência alinhado em pt-BR + **smoke auditivo humano obrigatório**. Sem classificador automático de sotaque no MVP. Não assumir que “Portuguese” = pt-BR.

**Narrator:** slot reservado `narrator` fora do pool de personagens (nunca selecionado para character assignment).

### D5 — Perfil vocal do LLM (hints semânticos)

**Escolha:** Estender `story_updates.characters` com `voice_profile` opcional (`gender`, `age_range`, `pitch`, `pace`, `energy`, `texture`, `personality[]`). `language` canônico do pipeline = `pt-BR` (default; não confiar no LLM para mudar locale).

**Mapeamento:** `BankVoiceGenerator` traduz hints → filtros/score no catálogo (ex. gender → pool; pitch/age → tags). Campos desconhecidos são ignorados com log; perfil ausente → atribuição determinística pelo `character_id` apenas.

**Por quê:** O LLM não precisa conhecer o backend; a abstração traduz.

### D6 — Materialização por personagem + seed determinístico

**Escolha (fechada):** materializar **sempre por personagem** no `VoiceRegistry` (`voices/<character_id>/`), copiando a base selecionada. `voice_map[character_id] = character_id` (chave estável). Vozes já persistidas **sempre vencem** qualquer reatribuição futura do algoritmo.

`metadata.json` MUST preservar:

- `language: "pt-BR"`
- `base_voice_id` (qual slot do banco originou a cópia)
- proveniência de geração (`generator`, `generator_version`, `seed`, `bank_version` quando aplicável)

Derivação de seed via `blake2b` (ou SHA-256) estável:

```text
seed_material = f"{character_id}|{profile_canonical_json}|{bank_version}|pt-BR"
seed = int.from_bytes(blake2b(seed_material, digest_size=8).digest(), "big") % 2**31
```

**Não usar** `hash()` built-in do Python.

### D7 — Resolução de path (prioridade)

**Escolha:**

1. Override usuário `./references/<voice_id>/`
2. Registry cache `~/.cache/audiobook-ai/voices/<voice_id>/` (ou `--cache-dir`)
3. Assets empacotados `assets/voices/<voice_id>/` (bases + narrator)
4. Falha explícita se nada pt-BR válido — **sem** fallback para clipe inglês legado

**BREAKING soft:** o fallback atual “voice desconhecida → narrator (mesmo se inglês)” deixa de ser aceitável. Narrator empacotado MUST ser trocado por pt-BR nesta change.

### D8 — Falhas

**Escolha:** Se geração/atribuição falhar (banco vazio, perfil incompatível sem candidatos, I/O):

1. Não atribuir voz aleatória silenciosa.
2. Registrar erro + character_id + motivo.
3. Permitir retry na próxima execução (sem entrada podre em `voice_map`).
4. Fallback opcional **somente** para voz base pt-BR documentada (ex. `narrator` pt-BR) **com log de aviso**, e nunca para referência marcada `language != pt-BR`.

### D9 — Script de seed Piper/Kokoro (build-only) e VRAM

**Escolha (fechada):** incluir script opcional de reprodutibilidade/build (Piper `pt_BR` e/ou Kokoro BR) no repo. Assets pt-BR **pré-gerados e validados** vão empacotados com a aplicação. O script MUST NÃO ser necessário no hot path do audiobook.

MVP não carrega Piper/Kokoro/Parler no pipeline de geração do livro. ModelManager/Fish Speech permanecem inalterados no hot path.

### D10 — Esgotamento do pool de bases

**Escolha (fechada):** ao atribuir voz a um personagem novo:

1. Preferir bases **compatíveis ainda não usadas** no livro (`voice_map` / registry do work-dir).
2. Quando o pool compatível estiver esgotado, **reuse é permitido**, escolhido de forma **determinística** (mesmo mecanismo de seed/hash).
3. A atribuição resultante é materializada imediatamente no registry e permanece estável pelo audiobook.
4. Narrator continua excluído do pool de reuse para personagens.

Reuse compartilha `base_voice_id` entre personagens distintos, mas cada um mantém pasta própria no registry (cópias independentes + provenance).

### D11 — Alternativas futuras (não MVP)

- **Parler-TTS pt-BR:** backend `VoiceGenerator` experimental pós-MVP, gated por smoke.
- **Qwen3-TTS VoiceDesign:** só após validação empírica de sotaque BR no hardware do projeto; default rejeitado.
- Classificador automático de sotaque pt-BR: fora do MVP (D4).

## Risks / Trade-offs

- **[Cobertura limitada do banco]** → reuse após 5 personagens → Mitigação: pool extensível sem hardcode; preferir unused; reuse determinístico + materialização estável (D10); tags de perfil.
- **[Assets com licença inadequada]** → Mitigação: registrar licença em `metadata.json`; preferir Piper/Kokoro com licenças claras; script de seed no repo.
- **[Fish Speech degrada ref curta]** → Mitigação: refs ≥3–10s de fala limpa pt-BR; frase canônica no `.lab`.
- **[LLM omite voice_profile]** → Mitigação: assign só por `character_id` ainda funciona; perfis são otimização.
- **[story.json antigo com voice_01 fantasma]** → Mitigação: na resolução, se pasta inexistente / language inválida, regenerar ou falhar com mensagem clara (sem clone inglês).
- **[Percepção subjetiva de “distinctness”]** → Mitigação: smoke com 3 falantes obrigatório; testes só cobrem identidade/persistência.

## Migration Plan

1. Substituir `assets/voices/narrator/` por ref pt-BR + atualizar `.lab`.
2. Adicionar bases `assets/voices/base_*` (ou catálogo JSON + pastas) com metadata.
3. Deploy de código: `ensure_voice` passa a chamar registry/generator.
4. Usuários com `out/story.json` antigo: próxima geração que encontrar `voice_id` sem asset pt-BR reatribui/materializa (log); ou documentar apagar `voice_map` para regenerar.
5. Rollback: reverter change; assets antigos inglês **não** devem voltar como default se a correção pt-BR já foi mergeada — preferir manter narrator pt-BR.

## Open Questions — Resolved

| Questão | Decisão |
|---------|---------|
| Tamanho mínimo do banco MVP | **6** total: 1 narrator + 5 bases de personagem. Banco extensível; tamanho MUST NÃO ser hardcoded na lógica de atribuição (D4). |
| Materializar por personagem vs compartilhar base IDs | **Materializar por personagem** no registry. Persistido sempre vence reatribuição futura. `metadata.json` MUST guardar `base_voice_id` + proveniência (D6). |
| Script Piper/Kokoro | **Sim**, ferramenta opcional de build/reprodutibilidade. Assets pré-gerados validados vão no app. Script nunca no hot path (D9). |
| Validação automática de sotaque pt-BR | **Não** no MVP. Validação = metadata + proveniência + texto alinhado pt-BR + smoke auditivo humano obrigatório (D4). |
| Mais personagens que bases | Preferir bases compatíveis **unused**; depois **reuse determinístico**; persistir imediatamente e manter estável (D10). |
