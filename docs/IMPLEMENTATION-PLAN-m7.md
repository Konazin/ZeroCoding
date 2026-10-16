# Plano de implementação do M7 — revisão em 2026-10-16

Este plano operacionaliza [ROADMAP-m7.md](ROADMAP-m7.md), sem substituir a ordem ou os critérios daquele documento. O código partiu do commit `41d224f` da branch `development`, com M1–M6 implementados. O M5 mediu apenas Ornith, em tarefas sintéticas pequenas. Os arquivos locais de Playwright e `.github/workflows/playwright.yml` estão fora do Git e não integram o runtime Python; foram preservados.

## Atualização em 2026-10-16

M7.1 está coberto por testes de pipe e PTY, incluindo aprovações, cancelamento e retomada com ferramentas externas; o M7.2 tem um harness de 15 tarefas. M7.3 e M7.4 estão implementados com endpoints/SSE simulados, mas sem medição ou geração no servidor local. M7.9 inclui defaults e skills como recursos de pacote e um teste fora do checkout por cópia isolada. O ambiente não contém `setuptools`/`wheel`, portanto o wheel ainda não foi construído. A suíte automatizada usa serviços falsos; o mega teste local permanece pendente.

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
| **M7.2 — benchmark** | **Harness implementado** em `scripts/m7_bench.py` com 15 tarefas, verificadores independentes e 5 repetições padrão; mede sucesso, faixa entre tentativas, chamadas inválidas, aprovações, tempo e tokens. | Execução contra Ornith e baseline publicada continuam pendentes; não executar antes do mega teste. |
| **M7.3 — tokens e histórico** | **Implementado:** `/apply-template` + `/tokenize`, incluindo schemas, cache e fallback. `fit_messages` mantém turnos de ferramenta e pedido atual íntegros, com erro claro se não couber. Fallback ainda não foi calibrado por medição real. | Medir erro ≤3% nas classes do roadmap e comparar com baseline; manter 4.096 tokens até essa medição. |
| **M7.4 — streaming/cancelamento** | **Implementado com mocks:** SSE no provider, remontagem de tool calls e TTFT; raciocínio não é exibido; cancelamento fecha a resposta e falha de stream limpa texto parcial antes do fallback. Streaming continua opt-in e desativado por padrão. | Confirmar cancelamento no llama-server e paridade no benchmark. Cancelamento HTTP bufferizado/MCP segue fora deste incremento. |
| **M7.5 — orientação** | A/B do resumo compacto do workspace, com 5 repetições por tarefa e limite de tokens do roadmap. | Adotar apenas se ganho superar a variância e não houver regressão; registrar resultado negativo se não superar. |
| **M7.6 — sandbox opcional** | Se a medição de uso justificar, aplicar `bwrap` em comando, hook e servidor MCP com escopo de filesystem e rede explícitos. | Testes de isolamento e tarefas usuais do benchmark; ausência de `bwrap` falha de modo claro quando habilitado. |
| **M7.7/M7.8 — condicionais** | Comparar outros modelos só após atualização da decisão em `context.md`; compactar histórico só se métricas reais mostrarem >10% de turnos com `trimmed_messages > 0`. | Tabelas comparativas ou decisão registrada de não ativar; nenhuma implementação especulativa. |
| **M7.9 — liberação** | **Parcialmente implementado:** defaults e skills entram no package-data e usam `importlib.resources`; `INSTALL.md` atualizado; CI Python existente. Teste importa uma cópia isolada fora do checkout. | Ainda falta construir/instalar o wheel e executar `zc doctor` + turno falso após instalação. Sem versão/changelog de release até os gates M7.2–M7.4 passarem. |

## Regras de execução

Cada etapa preserva os arquivos locais não versionados, fecha com teste pertinente, suíte completa e registro em `context.md`. A partir do M7.2, comparar também com o benchmark e o M5; quando o servidor Ornith não estiver disponível, registrar a etapa como pendente de validação real, sem declarar o marco concluído. Não alterar modelo padrão, prompt de produção nem orçamento por intuição. O roadmap pede revisão do usuário entre etapas; entregar evidências e diff concretos para essa revisão.
