# Handoff da sessão — mega teste M7 e validação M8

Atualizado em 2026-10-16, branch `development`. O briefing completo está em [`MEGA-TEST-M7-M8-2026-10-16.md`](MEGA-TEST-M7-M8-2026-10-16.md).

## Ponto de parada

- A suíte automatizada M7 + M8 passou: **239 testes e 10 subtestes**.
- M7.2 foi medido em 15 tarefas × 5 repetições. Depois de alinhar o enunciado/verificador de `change_signature` e repetir esse caso, o agregado é 64/75 sem streaming (85,3%) e 65/75 com streaming (86,7%). `change_signature` passou 5/5; `run_tests` falhou 0/5. Chamadas inválidas: 2 sem streaming e 6 com streaming. Os agregados corrigidos estão nos JSONs com `-corrected`.
- M7.3: `/apply-template` + `/tokenize` funcionaram no servidor real, mas o fallback heurístico errou de 7,3% a 31,0% por classe, acima do limite de 3%. O orçamento continua 4096.
- M7.4: M5 passou 21/21 com e sem streaming. O streaming teve 2 erros de ferramenta, `usage` ausente, TTFT mediano de 6,35 s (pior 83,36 s). Cancelamento SSE real passou e o slot do llama-server ficou ocioso; o primeiro texto levou 25,7 s. `streaming_enabled` segue `false`.
- M7.5 não avançou porque os gates anteriores falharam. O A/B existente não corresponde à hipótese da árvore compacta do workspace, só roda uma repetição e deixa um diretório temporário global.
- M7.6 não avançou porque `run_tests` passou 0/5; M7.7 segue limitado ao Ornith pelo `context.md`; M7.8 não tem gatilho de métricas comprovado; M7.9 aguarda CI/wheel (`setuptools` e `wheel` ausentes localmente).

## Relatórios e harnesses

- [M7.2 sem streaming](m7-ornith-1.5-9b-q5_k_m-mega-20261016.json)
- [M7.2 com streaming](m7-ornith-1.5-9b-q5_k_m-mega-20261016-streaming.json)
- [M5 sem streaming](m5-ornith-1.5-9b-q5_k_m-mega-20261016-results.json)
- [M5 com streaming](m5-ornith-1.5-9b-q5_k_m-mega-20261016-streaming-results.json)
- [Calibração de tokens variada](m7-ornith-token-calibration-mega-20261016-v2.json)
- [Cancelamento SSE real](m7-stream-cancel-mega-20261016.json)
- Harnesses novos: [`scripts/m7_token_eval.py`](../scripts/m7_token_eval.py) e [`scripts/m7_stream_cancel_check.py`](../scripts/m7_stream_cancel_check.py).

## Próximos passos sugeridos

1. Melhorar o harness M7.2 para preservar, por opção explícita, diffs/resumos seguros de tentativas que falham; o relatório atual mede as falhas, mas não guarda material suficiente para diagnosticar `change_signature`/`run_tests`.
2. Corrigir ou redesenhar o fallback de tokens e repetir a calibração com prompts distintos antes de alterar orçamento.
3. Corrigir métricas SSE (`usage`, tokens e TTFT) e reavaliar streaming; mantê-lo desativado até a paridade ser limpa.
4. Depois de M7.2–M7.4 aprovados, alinhar implementação/roadmap do M7.5 e corrigir seu harness antes de executar o A/B.
5. Confirmar instalação não editável e `zc doctor`/turno falso pela CI para fechar M7.9 e a validação empacotada do M8.

## Estado do ambiente e arquivos

- No último diagnóstico do host, `llama-server` já estava rodando com o Ornith em Vulkan0; havia 477 MiB livres na RX 5700. O teste não iniciou nem encerrou esse servidor.
- Não foi feito commit. Preserve o trabalho já existente do usuário, incluindo `.github/workflows/playwright.yml`, `e2e/`, `package.json`, `package-lock.json`, `playwright.config.ts` e demais mudanças já presentes na árvore de trabalho.
