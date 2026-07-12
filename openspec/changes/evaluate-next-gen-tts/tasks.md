## 1. Preparação (corpus e avaliação cega)

- [ ] 1.1 Criar e versionar o corpus oficial de benchmark (2–3 speaker refs ~15 s pt-BR com texto alinhado; conjunto de frases; passagem ~10 min de áudio) sob path acordado (ex.: `benchmarks/tts-next-gen/`) com README de uso
- [ ] 1.2 Definir e versionar o checklist de avaliação cega (2 avaliadores, amostras sem identificação do motor, critérios objetivos: naturalidade, prosódia, sotaque pt-BR, inteligibilidade, clonagem, consistência)
- [ ] 1.3 Preparar estrutura de resultados reproduzíveis (`results/` por candidato: métricas, logs VRAM, notas de eliminação) sem alterar código de produção

## 2. Candidatos e isolamento

- [ ] 2.1 Confirmar lista mínima (Fish S1-mini, Fish S2-pro, CosyVoice 3, Qwen3-TTS, IndexTTS2) e opcionais (XTTS v2, F5-TTS, Kokoro) com versões/pin a documentar
- [ ] 2.2 Preparar ambientes isolados de spike (venv/cache separados dos extras de produção) para evitar quebrar o hot path

## 3. Fase 0 — Viabilidade

- [ ] 3.1 Executar Fase 0 em cada candidato no hardware oficial (ROCm, local, Linux, offline, português, clonagem)
- [ ] 3.2 Documentar eliminações imediatas com justificativa técnica; publicar lista de sobreviventes

## 4. Fase 1 — Qualidade

- [ ] 4.1 Sintetizar o corpus de frases + refs com todos os sobreviventes (mesmos textos/refs)
- [ ] 4.2 Conduzir avaliação cega com 2 avaliadores e o checklist oficial (gate pt-BR)
- [ ] 4.3 Eliminar FAIL de pt-BR / clonagem / qualidade; registrar fichas parciais

## 5. Fase 2 — Performance

- [ ] 5.1 Medir load/init, RTF oficial (`t_síntese / duração_áudio`), tempo para ~10 min de áudio, CPU/GPU, VRAM média e pico
- [ ] 5.2 Classificar soft reclaim vs hard reclaim (exit de processo) sob ROCm
- [ ] 5.3 Selecionar finalistas para stress (sugestão ≤2); eliminar o restante com números

## 6. Fase 3 — Stress

- [ ] 6.1 Executar ~200 SpeechChunks (partição documentada do corpus) nos finalistas
- [ ] 6.2 Registrar growth/fragmentação/OOM/restarts; eliminar instáveis

## 7. Fase 4 — Stress profundo (somente finalistas)

- [ ] 7.1 Executar 1000 SpeechChunks nos finalistas restantes
- [ ] 7.2 Executar 5000 SpeechChunks (ordem de magnitude de um livro) nos que sobreviverem a 7.1
- [ ] 7.3 Consolidar estabilidade longa vs baseline Fish

## 8. Relatório e decisão

- [ ] 8.1 Consolidar benchmarks na tabela comparativa (qualidade, pt-BR, clonagem, RTF, load, VRAM, estabilidade, integração, manutenção)
- [ ] 8.2 Produzir relatório comparativo completo com fichas por candidato (limites, forças, fraquezas)
- [ ] 8.3 Emitir **uma** recomendação arquitetural oficial: KEEP Fish Speech | REPLACE Fish Speech | REPLACE Voice Design | REPLACE toda a stack de voz — com justificativa ancorada só nas evidências
- [ ] 8.4 Confirmar explicitamente que nenhuma mudança de produção foi feita nesta change; apontar próxima change de implementation apenas se a decisão ≠ KEEP (ou se KEEP exigir follow-ups não-migratórios documentados)
