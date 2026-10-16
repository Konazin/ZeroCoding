# M6 — Extensibilidade (implementado em 2026-10-16)

**Estado:** os pré-requisitos e os quatro itens (M6.1–M6.4) estão implementados, todos desligados por padrão. Resultados medidos na seção "Resultado da implementação" ao final. O texto abaixo é o plano original, mantido como registro das decisões.

Este plano detalha o M6 de [`ROADMAP-extension.md`](ROADMAP-extension.md): hooks, MCP, subagentes e plugins. O `ROADMAP.md` os deixa **fora do núcleo** e só admite entrada com necessidade comprovada e custo aceitável. Este documento define o que significa "comprovada" e "aceitável" com os números medidos no M3–M5, e a ordem de entrada.

## Premissas medidas (base para as decisões)

| Fato | Valor | Fonte |
|---|---|---|
| Orçamento de entrada por chamada | 4 096 tokens (janela do servidor: 8 192) | `config/default.yaml` |
| Custo dos 6 schemas de ferramenta atuais | ≈ 400 tokens (~65 por ferramenta) | `/tokenize`, M3 |
| Prompt base sem ferramenta | ≈ 770 tokens | `m5-ornith-…-results.json` |
| Geração | ≈ 22 tokens/s | M5 |
| Duração de um turno com ferramentas | 4–30 s | M5 |
| Baseline de qualidade | 21/21 casos, 2 erros em 35 chamadas | M5 |
| Seleção dinâmica de ferramentas | −17% de prompt, mas 5/8 vs 7/8 de acerto | M3, `dynamic_context_ab.py` |
| Servidor | 1 modelo, sem paralelismo útil, VRAM ~89% usada | M5 |

Consequência: **cada schema novo custa ~65 tokens em toda chamada** e a janela útil é pequena. Extensibilidade que aumente o prompt de forma fixa degrada o produto; o desenho precisa ser "paga só quando usada".

## Critérios de entrada (valem para cada item)

Um item só vira implementação se, antes, houver:

1. **Necessidade concreta:** uma tarefa real do usuário que o núcleo (M1–M5) não resolve, registrada em `context.md`. "Seria legal" não conta.
2. **Custo medido:** com o recurso **ligado e sem uso**, o prompt cresce no máximo **+10% do orçamento de entrada (≈ 410 tokens)**, medido com `TokenCounter`. Ligado e usado, o limite é declarado no plano do item.
3. **Sem regressão:** `scripts/m5_eval.py` continua em 21/21 e a suíte unitária passa. Recurso desligado = comportamento idêntico ao de hoje.
4. **Segurança testada:** aprovação, Plan mode, sandbox de caminhos e ambiente mínimo continuam valendo para o que o recurso executar; há testes de recusa e de bloqueio no Plan.
5. **Desligado por padrão** e configurável em YAML.

## Pré-requisitos (do M4.5, ainda não feito)

Não implementados hoje e necessários antes de ferramentas externas lentas:

- **Cancelamento do turno (Ctrl+C):** hoje não há. Ferramenta MCP ou hook travado não pode prender a TUI. Obrigatório antes do item 2.
- **Métricas locais por turno** (tokens reais, latência, erros em `.zerocoding/`, sem versionar): necessárias para checar os critérios 2 e 3 em uso real, não só no harness.
- **Compactação de histórico:** só se o uso real mostrar sessões estourando o orçamento; o M5 nunca o atingiu, então não é pré-requisito automático.

## Ordem proposta (do mais barato e seguro ao mais caro)

### M6.1 — Hooks (primeiro)

- **O quê:** comandos do usuário em YAML disparados em eventos já existentes: antes/depois de ferramenta e fim de turno. Casos de uso: rodar formatador ou testes após `edit_file`, bloquear um padrão de comando, notificação.
- **Por que primeiro:** custo de prompt **zero** (não aparece para o modelo), reaproveita `AgentEvent` e a política de `run_command`.
- **Desenho:**
  - Bloco `hooks:` no YAML (`pre_tool`, `post_tool`, `turn_end`), cada hook com `match` (nome de ferramenta/glob de caminho), `command`, `timeout`, `blocking`.
  - `pre_tool` bloqueante pode **recusar** a chamada (saída ≠ 0 vira resultado legível ao modelo). Nunca pode **aprovar** nada que exija aprovação do usuário.
  - Hooks rodam sob `CommandPolicy` (mesmo deny/ambiente mínimo/timeout/limite de saída). Hook é código do próprio usuário (config dele), mas não herda segredos.
  - Mudança no código: um módulo `core/hooks.py` chamado de `Agent._run_tool_call`; sem mexer em providers.
- **Saída:** testes de ordem de execução, recusa por `pre_tool`, timeout, hook que falha sem derrubar o agente, Plan mode (hooks de escrita não rodam se a ferramenta foi bloqueada). Custo de prompt medido = 0.

### M6.2 — Cliente MCP (stdio), somente leitura primeiro

- **O quê:** conectar servidores MCP locais (stdio) e expor suas ferramentas ao agente.
- **Risco principal:** tokens. Um servidor MCP típico declara dezenas de ferramentas com schemas longos; sem controle, estoura o orçamento de 4 096.
- **Desenho:**
  - **Allowlist obrigatória por servidor e por ferramenta** no YAML; nada é exposto por padrão. Teto configurável de ferramentas MCP expostas (padrão 4) e de tokens de schema (padrão ≤ 400, medido com `TokenCounter`); acima disso, o servidor é recusado com mensagem clara.
  - **Descrições encurtadas** (corte por tokens) e remoção de campos opcionais verbosos do schema.
  - **Toda chamada MCP passa por `approve` por padrão**, com a ferramenta, o servidor e os argumentos no preview; `read_only: true` explícito por ferramenta na allowlist dispensa o prompt, e só essas ferramentas ficam disponíveis no Plan.
  - **Resultado MCP é dado não confiável:** cortado em `max_output_chars`, marcado como saída de ferramenta externa, nunca interpretado como instrução (mesmo cuidado que o prompt já tem com conteúdo de arquivo).
  - Processo do servidor MCP lançado com **ambiente mínimo** (só o que o YAML liberar), sem shell, com timeout de inicialização e de chamada; encerrado ao fim da sessão. Depende do cancelamento do turno (pré-requisito).
  - Dependência: implementar o protocolo stdio/JSON-RPC mínimo em código próprio (~200 linhas) em vez de adicionar o SDK, a menos que a medição mostre que o SDK é necessário. Decisão registrada em `context.md`.
- **Saída:** servidor MCP de teste (fake em Python no `tests/`) cobrindo allowlist, teto de tokens, aprovação/recusa, Plan, timeout, servidor que morre no meio, injeção em resultado; `m5_eval.py` em 21/21 com um servidor MCP configurado e ocioso, e custo medido ≤ 410 tokens.

### M6.3 — Subagentes (condicional; provável adiamento)

- **O quê:** delegar uma exploração a um agente com contexto próprio e devolver só o resumo.
- **Por que é o mais incerto aqui:** há **um modelo e uma slot** em hardware já no limite. Subagentes seriam **sequenciais**, então não ganham tempo; só ganham **contexto** (a exploração não polui o histórico principal). O M5 nunca mostrou pressão de contexto (maior total de um turno: 4 846 tokens somados em várias chamadas, nenhum estouro do orçamento por chamada).
- **Gatilho para sair do papel:** métricas de uso real (M4.5) mostrando turnos que descartam histórico ou perdem o pedido atual por exploração longa em **mais de ~10% dos turnos**. Sem isso, não implementar.
- **Se for implementado:** um único tipo, "explorer" **somente leitura** (list/search/read), contexto novo, orçamento próprio (≤ 1 024 saída, ≤ 4 rodadas), retorno limitado a ~300 tokens, sem acesso a escrita/comando/MCP com efeito colateral, e sem aninhamento (subagente não cria subagente). A forma mais barata de testar a hipótese é **resumir a exploração dentro do mesmo agente** antes de criar um segundo.

### M6.4 — Plugins (por último; talvez só convenção)

- **O quê:** empacotar skills + hooks + config MCP num diretório instalável.
- **Desenho mínimo:** um plugin é uma **pasta declarativa** (`skills/*.md`, `hooks.yaml`, `mcp.yaml`) carregada de `~/.zerocoding/plugins/<nome>/`. **Sem execução de código Python do plugin**; o que ele executa passa pelos mesmos hooks/MCP já protegidos (M6.1/M6.2). Instalar = copiar a pasta; remover = apagar.
- **Quando:** só depois que M6.1 e M6.2 existirem e houver demanda de compartilhar configurações. Antes disso, `skills/` e o YAML já cobrem o caso.

## Fora do escopo do M6

- Plugins com código arbitrário, marketplace, atualização automática, execução remota.
- Servidores MCP remotos (HTTP/SSE) e autenticação OAuth: só stdio local, enquanto não houver necessidade comprovada.
- Subagentes paralelos (o servidor tem uma slot).
- Troca de modelo: continua regida por `context.md`; a comparação de modelos do M5 segue pendente e independente do M6.

## Riscos e mitigação

| Risco | Mitigação |
|---|---|
| Schemas externos estouram o orçamento de 4 096 tokens | Allowlist, teto de ferramentas e de tokens, descrições encurtadas, teste de custo ocioso |
| Prompt injection via resultado de ferramenta MCP | Resultado tratado como dado, truncado, aprovação por padrão, Plan só com ferramentas `read_only` |
| Hook ou servidor travado prende a TUI | Cancelamento de turno (pré-requisito), timeouts, processos encerrados com a sessão |
| Vazamento de segredos para processos filhos | Ambiente mínimo com `env_passthrough` explícito (mesma política do `run_command`) |
| Regressão do núcleo | Recurso desligado por padrão; `m5_eval.py` 21/21 como portão de cada item |
| Escopo crescendo antes da necessidade | Critérios de entrada obrigatórios; M6.3 e M6.4 condicionais |

## Sequência e estimativa de esforço

| Etapa | Depende de | Tamanho relativo |
|---|---|---|
| Pré-requisito: cancelamento + métricas por turno | M4 | médio |
| M6.1 Hooks | M4 (eventos, `CommandPolicy`) | pequeno |
| M6.2 MCP stdio somente leitura | M6.1, cancelamento | grande |
| Revisão com dados de uso real | M6.1–M6.2 + métricas | pequeno |
| M6.3 Subagente explorer | gatilho de uso real | médio, condicional |
| M6.4 Plugins declarativos | M6.1, M6.2 | pequeno, condicional |

Cada etapa termina com: suíte verde, `scripts/m5_eval.py` em 21/21, custo de prompt medido, `context.md` atualizado e o usuário revisando antes da seguinte.

## Resultado da implementação (2026-10-16)

| Item | Entregue | Arquivos principais |
|---|---|---|
| Cancelamento | `Ctrl+C` na TUI e `CancelToken` cooperativo; turno cancelado ou com erro não grava histórico | `core/cancel.py`, `core/agent.py`, `cli.py` |
| Métricas por turno | JSONL só com números; `/metrics`; conta histórico cortado (gatilho do M6.3) | `core/metrics.py`, `commands.py` |
| M6.1 Hooks | `pre_tool` (bloqueante opcional), `post_tool` (só falha chega ao modelo), `turn_end`; sob `CommandPolicy`, ambiente mínimo, stdin JSON | `core/hooks.py` |
| M6.2 MCP stdio | cliente próprio (~200 linhas, sem SDK), allowlist obrigatória, `max_tools`/`max_schema_tokens`, schemas compactados, aprovação por padrão, saída truncada e rotulada como dado externo, Plan só com `read_only` | `mcp/client.py`, `mcp/manager.py`, `core/tools.py` |
| M6.3 Subagente | `explore` somente leitura, contexto novo, 4 rodadas, resumo ≤ 1 200 caracteres, sem aninhamento; tokens somados ao turno pai; **desligado por padrão** | `core/subagent.py` |
| M6.4 Plugins | pastas declarativas (skills + hooks + MCP), habilitação explícita, `{plugin_dir}`, nenhum Python executado | `core/plugins.py`, `core/bootstrap.py` |

### Medições (Ornith, mesma máquina e harness do M5)

| Critério de entrada | Resultado |
|---|---|
| Custo ocioso ≤ ~410 tokens | **+228 tokens por chamada** com 2 ferramentas MCP + `explore` ligados (caso `direct`: 771 → 999) |
| Sem regressão no M5 | **21/21** com extensões ligadas e ociosas; 40 chamadas de ferramenta, 0 erros (`docs/m5-ornith-1.5-9b-q5_k_m-extensions-results.json`) |
| Desligado por padrão | sim; sem configuração, o agente expõe só as 6 ferramentas nativas e não carrega nada |
| Segurança testada | recusa, bloqueio no Plan, ambiente mínimo, allowlist, tetos, injeção em saída MCP, servidor que morre, hooks que falham/estouram o tempo |

O custo é por chamada: um turno com 4 chamadas ao modelo paga ~4 × 228 tokens a mais. As durações do caso `plan_blocks_write` (26 s → 43 s) e do comando aprovado (14,7 s → 20,6 s) subiram; com 3 repetições e um modelo que escolhe caminhos diferentes a cada vez, não dá para separar o efeito do custo extra de prompt da variância. Os demais casos ficaram dentro de ~1 s.

### Verificado de ponta a ponta na TUI real (pty, Ornith, HOME isolado)

`/mcp`, `/hooks` e `/plugins` listam o estado; o modelo chamou `mcp__fake__echo` e devolveu o resultado exato; `explore` achou a definição e o chamador de uma função e o turno registrou `subagent_runs: 1` com tokens somados; edição aprovada com `Y` aplicou o diff e disparou o hook `post_tool`; `rm -rf build` foi barrado pelo hook `pre_tool` bloqueante sem pedir aprovação; `Ctrl+C` cancelou o turno e o `/metrics` registrou o cancelamento.

### Defeitos antigos encontrados e corrigidos no caminho

Os testes ponta a ponta na TUI real revelaram dois problemas do M1, ambos fora do M6:

1. **Toda aprovação falhava.** `confirm_action` registrava as teclas `s-y`/`s-n`, inválidas no prompt_toolkit 3.0.53 (o do `uv.lock`); o `ValueError` virava "Tool error" e nenhuma escrita ou comando podia ser aprovado na TUI.
2. **Qualquer texto aprovava.** O resultado era `bool(texto)`, então digitar algo e dar Enter (por exemplo o `/exit` seguinte) aprovava a ação. Agora só `Y` aprova; Enter ou outro texto recusa, como o roadmap do M1 já previa. `tests/test_tui_confirm.py` cobre os dois casos e falha no código antigo.

### Limites conhecidos

- A confiança em plugins e hooks é do usuário: habilitar um plugin executa os hooks e servidores dele sem aprovação por evento. Um hook ou servidor MCP vem de arquivo de configuração; se o agente puder gravar nesse arquivo (config dentro do workspace), a gravação passa pela aprovação normal de `write_file`/`edit_file`.
- O subagente não tem o gatilho de uso real do plano (>10% dos turnos cortando histórico): foi implementado por decisão do usuário, mas segue desligado por padrão e `/metrics` mostra `turns_with_trimmed_history` para avaliar quando ligar.
- Só servidores MCP stdio locais; sem HTTP/SSE nem OAuth. O cliente anuncia nenhuma capacidade (sem sampling, roots ou elicitation).
- Os testes de MCP usam um servidor falso em `tests/fixtures`; um servidor MCP de terceiros real não foi exercitado.
- O custo de +228 tokens foi medido com 3 ferramentas; ele cresce ~65 tokens por ferramenta adicional, até o teto de 400 tokens de schema de MCP.
