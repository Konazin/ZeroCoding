# Plano de implementação do M7 — revisão em 2026-10-16

Este plano operacionaliza [ROADMAP-m7.md](ROADMAP-m7.md), sem substituir a ordem ou os critérios daquele documento. O código partiu do commit `41d224f` da branch `development`, com M1–M6 implementados. O M5 mediu apenas Ornith, em tarefas sintéticas pequenas. Os arquivos locais de Playwright e `.github/workflows/playwright.yml` estão fora do Git e não integram o runtime Python; foram preservados.

## Atualização em 2026-10-16

M7.1 está coberto por testes de pipe e PTY, incluindo aprovações, cancelamento e retomada com ferramentas externas. O mega teste de 2026-10-16 executou M7.2–M7.4 contra o Ornith e reprovou os gates de benchmark, fallback de tokens e latência/observabilidade do streaming. Os relatórios estão em [`MEGA-TEST-M7-M8-2026-10-16.md`](MEGA-TEST-M7-M8-2026-10-16.md). A suíte automatizada M7+M8 passou 239 testes e 10 subtestes. M7.9 ainda aguarda CI; o ambiente não contém `setuptools` nem `wheel` para construir localmente.

## Estado verificado e riscos adicionais

- Baseline anterior às alterações do M7: `.venv/bin/python -m pytest -q` passou **159 testes**. `uv` não está disponível no ambiente; a suíte é executada pela `.venv`.
- **P0 — busca fora do workspace (corrigido):** `search_files` seguia links simbólicos e devolvia conteúdo externo. O walker agora ignora links de arquivo e diretório e a busca resolve novamente cada caminho antes de abrir. `tests/test_m4_workflow.py` cobre ambos os tipos de link.
- **P1 — edição sobre alteração concorrente (corrigido):** `write_file` e `edit_file` agora comparam identidade e conteúdo após a aprovação e antes de substituir; usam arquivo temporário no diretório de destino e recusam o preview obsoleto. Testes cobrem arquivo alterado e arquivo criado durante a aprovação. A validação evita a janela normal de espera pela aprovação; operações concorrentes arbitrárias ainda dependem do sistema de arquivos.
- **P1 — cancelamento e estado (parcial):** `run_command` e hooks encerram o grupo de subprocessos em timeout ou `KeyboardInterrupt`; o novo SSE fecha a resposta HTTP quando cancelado. Requests bufferizados e chamadas MCP ainda não são interrompidos pelo `CancelToken`. Cancelamento não desfaz efeitos de ações já aprovadas e executadas.
- **P1 — saída de comando sem limite de memória (corrigido):** novo `core/process.py` drena stdout/stderr continuamente e conserva apenas o limite configurado, também usado por hooks; o timeout mantém saída truncada e encerra o grupo de processo.
- **P1 — orçamento e protocolo (corrigido no código, validação de servidor pendente):** o déficit de ~26% com ferramentas já está registrado no M7. O contador aplica o template e inclui schemas; o ajuste do histórico remove turnos antigos em conjunto, preserva chamadas/resultados e não trunca o pedido atual. O limite de erro ≤3% ainda precisa de medição real.
- **P2 — divergência de aprovação (corrigido):** fallback e `prompt_toolkit` agora aceitam somente `Y`; cobertura inclui a rota de fallback e a integração TUI → agente → escrita.
- **P2 — instalação/documentação (parcialmente corrigido):** defaults e skills agora são recursos de pacote e os carregadores funcionam fora do checkout; `INSTALL.md` acompanha llama.cpp. Teste isolado usa cópia do pacote porque `setuptools`/`wheel` não estão disponíveis para construir o wheel neste ambiente.

## Sequência de implementação

| Etapa | Trabalho | Evidência de saída |
|---|---|---|
| **M7.1a — correções de fronteira** | **Concluído:** links simbólicos, snapshot após aprovação, escrita atômica, limite de saída de subprocesso e consistência de aprovação. | Testes reproduzem os defeitos corrigidos; suíte automatizada verde. |
| **M7.1 — integração e doctor** | **Concluído:** aprovação/recusa por pipe e PTY, Ctrl+C, tratamento dos slash handlers, `/new`, `/resume` com extensão e `zc doctor` com endpoints/MCP falsos. | CI Python sem servidor local; `doctor` distingue falha impeditiva de aviso. |
| **M7.2 — benchmark** | Agregado reconciliado em 15 tarefas × 5 repetições: **64/75 (85,3%)** sem streaming; **65/75 (86,7%)** com streaming. O verificador de `change_signature` tinha um literal não pedido; corrigido, o caso passou 5/5 nos dois modos. | Gate não aprovado: `run_tests` passou 0/5; chamadas inválidas foram 2 sem streaming e 6 com streaming. Ver os agregados corrigidos e manter M7.5 pendente. |
| **M7.3 — tokens e histórico** | `/apply-template` + `/tokenize` validados no servidor. Fallback medido em 20 prompts distintos: erro por classe entre 7,3% e 31,0%. `fit_messages` mantém turnos de ferramenta e pedido atual íntegros. | Gate ≤3% não aprovado; manter 4.096 tokens. Corrigir/redesenhar e reavaliar o fallback antes de alterar orçamento. |
| **M7.4 — streaming/cancelamento** | Cancelamento SSE real fechou a resposta e deixou o slot ocioso. M5 passou 21/21 nos dois modos; streaming teve 2 erros, tokens `usage` ausentes, TTFT mediano de 6,35 s e pior de 83,36 s. M7.2 reconciliado: 86,7% contra 85,3%, com mais chamadas inválidas. | Gate não aprovado; manter `streaming_enabled: false`. Primeiro texto do probe de cancelamento chegou em 25,7 s. |
| **M7.5 — orientação** | Não executado; depende dos gates anteriores. O roteiro atual de `dynamic_context` seleciona schemas/skills, mas o roadmap descreve injeção de árvore do workspace; o A/B existente também só repete uma vez e deixa diretório temporário. | Alinhar implementação e hipótese, corrigir harness e só então rodar cinco repetições por tarefa. |
| **M7.6 — sandbox opcional** | Não avançou. `run_tests` passou 0/5 no benchmark sem sandbox, então o pré-requisito de funcionamento de comandos não foi atendido. | Não aplicar `bwrap` até corrigir e medir novamente o fluxo de comandos. |
| **M7.7/M7.8 — condicionais** | Comparar outros modelos só após atualização da decisão em `context.md`; compactar histórico só se métricas reais mostrarem >10% de turnos com `trimmed_messages > 0`. | Tabelas comparativas ou decisão registrada de não ativar; nenhuma implementação especulativa. |
| **M7.9 — liberação** | **Parcialmente implementado:** defaults e skills entram no package-data e usam `importlib.resources`; `INSTALL.md` atualizado; CI instala o projeto sem modo editável, verifica `zc`/`zerocoding` e executa a suíte. Teste importa uma cópia isolada fora do checkout. | A CI ainda precisa confirmar o wheel instalado; falta executar `zc doctor` + turno falso após instalação. Sem versão/changelog de release até os gates M7.2–M7.4 passarem. |

## Regras de execução

Cada etapa preserva os arquivos locais não versionados, fecha com teste pertinente, suíte completa e registro em `context.md`. A partir do M7.2, comparar também com o benchmark e o M5; quando o servidor Ornith não estiver disponível, registrar a etapa como pendente de validação real, sem declarar o marco concluído. Não alterar modelo padrão, prompt de produção nem orçamento por intuição. O roadmap pede revisão do usuário entre etapas; entregar evidências e diff concretos para essa revisão.
