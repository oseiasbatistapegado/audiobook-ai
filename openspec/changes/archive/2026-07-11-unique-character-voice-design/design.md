## Context

O código e as specs main (pós-`auto-pt-br-character-voices`) implementam `BankVoiceGenerator`: seleção determinística em `assets/voices/*` + materialização no registry + reuse quando o pool esgota. Fish Speech já clona refs; LLM já pode emitir `voice_profile` opcional.

O requisito de produto corrigido exige **identidade vocal sintética única por personagem**, condicionada ao perfil semântico, em pt-BR, sem catálogo finito. Banco fixo deixa de ser estratégia primária.

Hardware alvo: AMD RX 7900 XTX 24 GB / ROCm. Voice Design e Fish Speech provavelmente não cabem juntos — handoff VRAM obrigatório.

## Goals / Non-Goals

**Goals:**

- Voice Design gera identidade + referência canônica pt-BR **uma vez** por personagem (scoped por `book_id`).
- Fish Speech permanece o único TTS do hot path do audiobook.
- Unicidade perceptiva mesmo com perfis semânticos similares (seeds/latents distintos).
- Persistência: `voices/<book_id>/<character_id>/` com `reference.wav`, texto alinhado, metadata auditável.
- Spike empírico Parler-TTS pt-BR antes de declarar production-ready; Qwen3-TTS VoiceDesign como fallback de pesquisa.
- Pipeline batch: descobrir faltantes → gerar todas → unload → Fish Speech.

**Non-Goals:**

- Banco finito como solução primária ou fallback de “sucesso”.
- GUI / API web / cloud TTS / celebridade / impersonação.
- Classificador automático de sotaque.
- Música / SFX / atuação emocional perfeita.
- Personagens persistentes entre séries (futuro).
- Rodar Voice Design por frase.

## Decisions

### D1 — Split Voice Design vs Fish Speech

**Escolha:** Dois estágios. Voice Design cria identidade + ref pt-BR; Fish Speech só clona.

**Por quê:** Separar “criar speaker” de “falar o livro” permite unload, evita custo por frase, e mantém o hot path já integrado.

**Alternativa rejeitada:** Um único modelo fazendo design + long-form (não é o stack atual; Fish Speech já é o TTS).

### D2 — Candidato MVP: Parler-TTS pt-BR

**Escolha:** Avaliar e, se o spike passar, implementar `ParlerVoiceGenerator` sobre `freds0/parler-tts-mini-v1.1-ptbr`.

**Por quê:** Combina pt-BR documentado, descrição textual de estilo, multi-speaker, local, Python, tamanho relativo menor.

**Gate:** Spike real (não docs). Critérios: pt-BR aceitável, unicidade com seeds distintos + perfis similares, aderência semântica aproximada, export de ref, clonagem Fish Speech **preservando** distinção, ROCm/VRAM.

### D3 — Alternativa: Qwen3-TTS VoiceDesign

**Escolha:** Só se Parler falhar critérios críticos. Mesmo protocolo de spike; atenção especial a sotaque pt-BR vs pt-PT.

**Por quê:** Pode oferecer voice design mais forte; Portuguese genérico ≠ BR.

### D4 — Abstração `VoiceGenerator` / `GeneratedVoice`

**Escolha:** Manter Protocol independente de backend. Implementação inicial `ParlerVoiceGenerator`. Factory deixa de defaultar `bank`.

`GeneratedVoice` (campos mínimos): `voice_id`, `character_id`, `language`, paths de ref + texto, `generator`, `generator_version`, `model_id`, `seed`, `voice_profile` snapshot.

Pipeline/registry NÃO importam APIs Parler/Qwen.

### D5 — Unicidade e seed

**Escolha:** Seed = BLAKE2b (ou SHA-256) de `book_id|character_id|canonical_profile_json|model_id|generator_version`. Nunca `hash()`.

Dois personagens com perfil similar MUST receber identidades distintas (seed diferente por `character_id`). Persistido vence regeneração.

Unicidade = identidade perceptiva do speaker, não só `voice_id`/cópia de WAV/rename de base.

### D6 — Escopo por `book_id`

**Escolha:** `~/.cache/audiobook-ai/voices/<book_id>/<character_id>/`.

**Por quê:** Evita colisão de `carlos` entre livros. Série global = futuro.

`book_id` = **BLAKE2b-128** (hex) do **conteúdo** do arquivo de input. Renomear ou mover o source MUST NÃO mudar o `book_id`.

### D7 — Referência canônica pt-BR

**Escolha:** Passagem(ns) canônica(s) pt-BR com `reference.txt`/`reference.lab` alinhado exatamente ao áudio.

**Duração:** alvo inicial **~15s**; faixa experimental aceita **10–30s**. O spike escolhe a menor duração que preserve identidade do speaker e qualidade de clonagem no Fish Speech.

Language canônico do produto = `pt-BR` (hard). Generic Portuguese insuficiente. **pt-BR borderline = FAIL** para default de produção (sotaque europeu dominante ou não-BR sistemático rejeita o backend; erros isolados de pronúncia podem ser avaliados como issues de texto/TTS).

### D8 — Fase de pipeline + VRAM

**Escolha:**

```text
interpret / discover characters
→ identify missing voices for book_id
→ load Parler (or selected backend)
→ generate all missing refs
→ persist
→ unload Voice Design + release VRAM
→ load Fish Speech
→ synthesize
```

Não alternar modelos por diálogo.

### D9 — Narrator

**Escolha:** Narrator gerado com um **`VoiceProfile` constante de MVP** (mesmo domínio de modelo dos personagens), otimizado para narração longa em pt-BR. MUST NÃO compartilhar identidade com personagem. Configurabilidade pública fica para depois, mas a arquitetura MUST permitir override futuro.

### D10 — Falhas

**Escolha:** Falha de geração → sem stock voice, sem share, sem inglês, sem `voice_id` simbólico sem ref. Preservar motivo; permitir retry. Personagem sem ref válida = unresolved.

### D11 — Deprecação do banco

**Escolha:** `BankVoiceGenerator` / assets empacotados NÃO são fallback de sucesso. Podem existir só como ferramenta de teste/dev. Specs de “prefer unused / reuse” e “banco extensível como capacidade” são removidas ou reescritas.

### D12 — Ordem de implementação

1. Spike standalone Parler (Carlos/João, mesma frase, seeds distintos).
2. Validar pt-BR + unicidade + Fish Speech preserva distinção + VRAM unload.
3. Registrar resultados no design (atualizar esta seção / Open Questions).
4. Se OK → `ParlerVoiceGenerator` + registry book-scoped + fase de pipeline.
5. Se não → spike Qwen; só então escolher default.
6. **Não** implementar banco como substituto.

## Risks / Trade-offs

| Risk | Mitigation |
|------|------------|
| Parler pt-BR fraco / pouco diverso | Spike gate; Qwen como plano B |
| Fish Speech colapsa duas refs | Critério go/no-go do spike; rejeitar backend |
| VRAM OOM no handoff | Fase batch + unload explícito + medição no spike |
| ROCm incompatível com Parler/HF | Spike early; pin versions; documentar workarounds |
| `book_id` instável entre runs | BLAKE2b-128 do conteúdo do input (rename/move não altera) |
| Qualidade semântica fraca (perfil → voz) | Aceite “aproximado” no MVP; prompt adapter testável |
| Specs/código bank ainda no main | Esta change supersede via deltas + troca de default |

## Migration Plan

1. Completar spike e registrar veredito no design.
2. Implementar gerador + registry book-scoped + fase pipeline.
3. Trocar default de `bank` → `parler` (ou nome do gerador escolhido).
4. Atualizar SMOKE/README: 3 vozes geradas; sem dependência de slots do banco.
5. Remover/ignorar requisitos de reuse de banco nas specs main no archive/sync.
6. Rollback: reverter default + manter refs já persistidas intactas (não apagar cache).

## Open Questions

### Resolved

- **Canonical `book_id`:** BLAKE2b-128 do conteúdo do arquivo de input. Rename/move do source MUST NÃO alterar o id.
- **Canonical reference duration:** alvo ~15s; faixa 10–30s; o spike fixa a menor duração que preserve identidade + clonagem Fish Speech.
- **Default narrator profile:** constante MVP no mesmo `VoiceProfile` dos personagens; configurabilidade pública adiada, arquitetura MUST permitir.
- **Partial Parler / borderline pt-BR:** borderline = **FAIL** para default de produção. pt-BR é hard requirement; sotaque não-BR sistemático ou pt-PT dominante rejeita o backend. Erros isolados de pronúncia MAY ser tratados à parte (texto/TTS).

### Still open

- **Parler spike auditory gate:** execução técnica feita (ver secção *Spike results*). Código de produto (`ParlerVoiceGenerator`, registry book-scoped, batch + unload) já integrado com default `parler`. Ainda falta veredito humano de: pt-BR (borderline=FAIL), unicidade Carlos vs João nas refs, e preservação da distinção após Fish Speech — necessário para fechar 1.6 go/no-go formal e smoke E2E 6.3.

## Spike results (ROCm / RX 7900 XTX 24GB)

Artefactos: `out/spikes/parler-voice-design/` (script `scripts/spike_parler_voice_design.py`, extra `voice-parler` + `parler-tts` via `--no-deps`).

| Stage | free MiB | torch_alloc MiB | Notes |
|-------|----------|-----------------|-------|
| Parler before_load | ~24514 | 0 | floor OK |
| Parler after_load | ~21836 | ~2473 | model ~2.5 GiB |
| Parler after_generate | ~19890 | ~2583 | peak during gen |
| Parler after_unload | ~23918 | ~110 | unload OK |
| Fish before_load | ~24514 | 0 | **must** be clean process / after Parler unload |
| Fish after_load | ~4558 | ~19229 | s2-pro ~19 GiB |
| Fish after_release (in-process) | ~9169 | ~14541 | **leak until process exit** |
| Fresh Python process | ~24504 | 0 | reclaim completo |

**Controles de VRAM no spike:** hard floor `MIN_FREE_VRAM_MIB=300`; antes de load Fish exige ≥22 GiB free; refs de clone truncadas a **6.0 s** (`clone_refs/`) — refs geradas ~9.1–9.4 s OOMavam o Fish na síntese; banco empacotado usa ~5–7 s.

**Durações:** Carlos ref 9.13 s / João 9.36 s; clones Fish ~7.7 s / ~7.2 s. Seeds BLAKE2b distintos (`382606864` / `1304973630`).

**Handoff:** Parler unload libera bem; Fish `release()` in-process **não** devolve VRAM de forma fiável — pipeline de produto MUST unload Voice Design e preferir processo limpo / exit antes do TTS (ou garantir reclaim equivalente).

**Proxy espectral (não substitui audição):** corr refs Carlos↔João ≈0.69; clones ≈0.72.