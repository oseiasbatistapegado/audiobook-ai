## Context

Stack atual de voz do produto:

```text
Parler-TTS (Voice Design, 1×/personagem)
        │ reference.wav + texto alinhado (pt-BR)
        ▼
Fish Speech (S1-mini default / S2-pro opcional)
        │ SpeechChunks → WAVs → merge M4B
        ▼
audiobook
```

Na RX 7900 XTX / ROCm, Fish (especialmente s2-pro) mostrou RTF alto (~13× documentado), pressão/fragmentação de VRAM e restarts de worker; volumes longos estimam-se em dias. O default já migrou para S1-mini + LLM menor, mas **não** há calibração comparativa multi-engine no hardware oficial.

Esta change é **somente pesquisa**: medir candidatos com protocolo fixo e emitir uma decisão arquitetural. Nenhuma alteração de produção.

## Goals / Non-Goals

**Goals:**

- Corpus oficial versionado + avaliação cega (2 avaliadores).
- Funil Fase 0–4 com kill gates; stress profundo só para finalistas.
- Fichas técnicas por candidato + tabela consolidada + relatório.
- Uma recomendação: KEEP Fish / REPLACE Fish / REPLACE Voice Design / REPLACE toda a stack.
- Separar soft reclaim vs hard reclaim (exit de processo) sob ROCm.

**Non-Goals:**

- Implementar novos backends no factory/workers/CLI de produção.
- Trocar Parler ou Fish no hot path nesta change.
- Otimizar RTF do Fish “no lugar” sem comparação.
- Aceitar números CUDA/NVIDIA como oficiais.
- Semantic chunking, multi-GPU, cloud TTS.

## Decisions

### D1 — Research change isolada de implementation change

**Escolha:** Congelar metodologia aqui; implementação de sucessor = change futura pós-relatório.

**Por quê:** Evita migração prematura no Cursor/PR antes de evidência.

### D2 — Hardware oficial único

**Escolha:** Ryzen 9 5950X + RX 7900 XTX 24 GB / ROCm / Linux / Python 3.12.

**Por quê:** É o ambiente de produção; ROCm é onde VRAM/unload falham de formas que CUDA esconde.

### D3 — Candidatos mínimos e opcionais

**Mínimo:** Fish S1-mini, Fish S2-pro, CosyVoice 3, Qwen3-TTS, IndexTTS2.

**Opcional:** XTTS v2, F5-TTS, Kokoro (e outros maduros se surgirem).

**Por quê:** Cobre baseline de produto, teto de qualidade Fish, e rivais open-source atuais. CosyVoice foi rejeitado historicamente por PT fraco — Fase 0/1 reabre com evidência, sem veto a priori.

### D4 — Corpus versionado (obrigatório)

**Escolha:** Commitar no repo:

| Artefato | Conteúdo |
|----------|----------|
| Speaker refs | 2–3 speakers; ~15 s; pt-BR; texto perfeitamente alinhado |
| Frases | diálogos, narração, números, datas, siglas, nomes, pontuação complexa, tom neutro |
| Passagem longa | texto → ~10 min de áudio (RTF, estabilidade, memória, degradação) |

Mesmas refs para todos os motores com clonagem; mesmos textos para todos.

Path sugerido (ajustável na task de corpus): `benchmarks/tts-next-gen/` (áudio, textos, `README` de uso) + `benchmarks/tts-next-gen/results/` para saídas.

### D5 — Avaliação cega

**Escolha:** Checklist curto; **2 avaliadores**; amostras **sem** identificação do motor; critérios objetivos alinhados a: naturalidade, prosódia, sotaque pt-BR, inteligibilidade, fidelidade de clonagem, consistência de identidade.

**pt-BR oficial:**

| Resultado | Critério |
|-----------|----------|
| PASS | sotaque brasileiro consistente |
| FAIL | português europeu dominante |
| FAIL | “Portuguese genérico” sem evidência pt-BR |
| FAIL | cloud-only |
| Não-eliminação automática | erros de pronúncia isolados claramente pontuais |

### D6 — Definição oficial de RTF

```text
RTF = tempo_de_síntese / duração_do_áudio_gerado
```

Ex.: 60 s para gerar 30 s de áudio → RTF = 2.0×.

Comparações MUST NÃO usar contagem de chunks, frases ou caracteres. Métrica comparável: **tempo por minuto de áudio produzido**.

### D7 — VRAM: além do pico

Classificar por candidato:

- VRAM média / pico
- crescimento progressivo / fragmentação
- após soft reclaim (in-process)
- após hard reclaim (encerramento do processo → retorno ao estado inicial)

Em ROCm, hard reclaim por exit de processo é o padrão que o produto já usa; o spike documenta se o candidato se comporta igual ou pior.

### D8 — Funil progressivo (custo)

```text
Fase 0  Viabilidade     → ROCm, local, Linux, offline, PT, clonagem
Fase 1  Qualidade       → corpus + avaliação cega pt-BR/clonagem
Fase 2  Performance     → load, RTF, ~10 min áudio, CPU/GPU/VRAM
Fase 3  Stress          → ~200 SpeechChunks; corta instáveis
Fase 4  Stress profundo → 1000 e 5000 chunks; só finalistas
```

Quem falha numa fase é eliminado; só finalistas pagam Fase 4 (~workload de livro).

**Partição para stress:** documentar no corpus/README como a passagem longa vira SpeechChunks (limites de tamanho alinhados ao espírito do produto), de modo que 200/1000/5000 sejam comparáveis entre motores mesmo que APIs nativas aceitem textos maiores.

### D9 — Critérios de eliminação imediata

Eliminar se:

- pt-BR inaceitável (gate acima);
- cloud obrigatório;
- sem clonagem de voz (quando o caso de uso exige clone);
- não funciona em ROCm (Fase 0);
- crescimento contínuo de VRAM / instável em long-form.

### D10 — Quatro decisões arquiteturais possíveis

Ao final, **uma** recomendação oficial:

1. **KEEP Fish Speech** — baseline (provavelmente S1-mini e/ou S2-pro conforme evidência) permanece no hot path.
2. **REPLACE Fish Speech** — Voice Design (Parler) pode permanecer; novo motor no papel de síntese longa/clonagem.
3. **REPLACE Voice Design** — Fish permanece; novo gerador de identidade.
4. **REPLACE toda a stack de voz** — Voice Design + TTS substituídos (um motor unificado ou novo par).

Decisão MUST citar o relatório; MUST NÃO ser escolhida antes das medições.

### D11 — Superfície de integração (avaliação, não implementação)

Avaliar (sem plugar no produto): API Python, worker isolado, unload/reclaim, SpeechChunk-friendly, HTTP/Docker obrigatório?, docs, manutenção ativa. O design atual (`TTSBackend` + worker + lease + hard reclaim por exit) é a **régua**, não o alvo de código nesta change.

### D12 — Isolamento de deps do spike

**Escolha:** ambientes/venvs ou dirs de cache separados dos extras de produção (`tts-fish`, `voice-parler`) sempre que houver conflito de torch/ROCm.

**Por quê:** Evitar quebrar o hot path enquanto se mede rivais.

## Risks / Trade-offs

| Risk | Mitigation |
|------|------------|
| Spike consome semanas na Fase 4 | Funil; só 1–2 finalistas no stress profundo |
| Julgamento subjetivo de pt-BR | Cego + 2 avaliadores + checklist fixo |
| Candidato bom em CUDA, morto em ROCm | Fase 0 no hardware oficial; CUDA só secundário |
| Tentação de integrar cedo | Cláusula de pesquisa no proposal + requirement em `specs/tts` |
| CosyVoice/Qwen “passam” com PT genérico | Gate pt-BR explícito (FAIL) |
| Chunk count enviesa RTF | RTF só por duração de áudio |
| Soft reclaim parece OK, hard reclaim falha | Medir ambos; espelhar lição Fish/ROCm |
| S1-mini já resolve e o spike “não muda nada” | KEEP é resultado legítimo |

## Migration Plan

1. Congelar esta change (proposal/design/specs/tasks).
2. Executar tasks: corpus → cego → fases 0–4 → relatório → decisão.
3. Arquivar a change de pesquisa com resultados.
4. **Se** a decisão ≠ KEEP: abrir **nova** change de implementation com escopo só do que a evidência mandar.
5. Rollback desta change: não há código de produção a reverter; descartar deps/caches do spike se desejado.

## Open Questions

- Path final exato do corpus no monorepo (`benchmarks/tts-next-gen/` vs sob `openspec/changes/evaluate-next-gen-tts/artifacts/`) — fixar na task 1.
- Lista final de opcionais (XTTS / F5 / Kokoro) após triagem Fase 0 de tempo disponível.
- Quantos finalistas máximos na Fase 4 (sugestão: ≤2) — confirmar ao fechar Fase 2.
