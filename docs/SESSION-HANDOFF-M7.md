# Handoff da sessão — M7

Atualizado em 2026-10-16, branch `development`. O M7 continua em andamento; não iniciar M8 enquanto os gates de validação do M7 estiverem pendentes.

## Ponto de parada

- M7.1: correções de confiabilidade, integração automatizada da TUI/PTY, retomada de extensões e `zc doctor` com serviços simulados implementados.
- M7.2: `scripts/m7_bench.py` implementa 15 tarefas verificáveis, com cinco repetições padrão e métricas. O benchmark contra o Ornith não foi executado.
- M7.3: contagem do prompt renderizado via `/apply-template` + `/tokenize`, schemas incluídos, cache/fallback, e ajuste de histórico que preserva chamadas/resultados e o pedido atual. Falta medir erro contra o servidor real; manter 4.096 tokens até lá.
- M7.4: SSE, TTFT, montagem de tool calls, cancelamento e fallback implementados e cobertos com mocks. Streaming continua desativado por padrão. Falta comparar qualidade/latência e validar cancelamento com o servidor.
- M7.9: defaults e skills incluídos como recursos de pacote e carregados fora do checkout; teste usa cópia isolada. Ainda falta construir/instalar wheel, rodar `zc doctor` e um turno após instalação; setuptools/wheel não estavam disponíveis neste ambiente.
- M7.5 depende do resultado do benchmark; M7.6 depende de evidência de uso; M7.7 requer decisão do usuário para permitir outros modelos; M7.8 só é acionado se `/metrics` mostrar mais de 10% dos turnos com mensagens aparadas.

## Validação desta sessão

`.venv/bin/python -m pytest -q`: **203 passed, 5 subtests passed**. Também passaram `git diff --check` e `compileall` para `src`, `tests`, `scripts/m5_eval.py` e `scripts/m7_bench.py`. Não houve geração com IA local, nem execução do benchmark ou do M5 nesta sessão. O mega teste local ainda precisa ser planejado antes dessas medições, conforme pedido do usuário.

## Próxima continuação

Planejar com o usuário o mega teste local e seus critérios, sem rodar geração até essa etapa estar definida. Depois, executar o M7.2 e o `scripts/m5_eval.py` contra o Ornith, registrar baseline e comparar os resultados necessários para fechar M7.3/M7.4. Só então decidir M7.5; respeitar os gatilhos condicionais dos outros itens e terminar M7.9 com um wheel instalado em ambiente limpo, `zc doctor` e turno falso. Não declarar M7 completo antes dos gates e não começar M8 enquanto M7 não fechar.

## Workspace a preservar

Arquivos Playwright encontrados no workspace (`.github/workflows/playwright.yml`, `e2e/`, `package.json`, `package-lock.json`, `playwright.config.ts`) e mudanças de `.gitignore` são alterações do usuário e devem ficar fora do commit M7. O workflow Python `.github/workflows/python-tests.yml` pertence ao M7. Não iniciar servidor local nem modelo durante esta continuação sem o plano do mega teste.
