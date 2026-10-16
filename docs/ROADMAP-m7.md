# M7 — Confiabilidade em uso real e qualidade medida (plano; não iniciado)

O M1–M6 entregaram a funcionalidade. O que o M6 mostrou é que **o que falta não é mais recurso, é confiança**: os dois defeitos mais graves encontrados (aprovação que nunca funcionava e aprovação por qualquer texto) estavam na TUI, passaram por revisão e pelos 100+ testes, e só apareceram ao dirigir a TUI de verdade. Além disso, a contagem de tokens está errada justamente no caso mais comum (com ferramentas) e não há como saber se uma mudança de prompt ou modelo melhora a qualidade. O M7 corrige isso **antes** de acrescentar mais capacidade.

## Evidências que motivam o plano

| Evidência | Fonte | Consequência |
|---|---|---|
| Aprovação na TUI falhou sempre (teclas inválidas) e aceitava texto qualquer; 100% dos testes unitários passavam | M6, `tests/test_tui_confirm.py` | A camada de TUI não tinha teste de integração; é o ponto mais perigoso (aprova escrita/comando) |
| Com ferramentas, o agente **subestima o prompt em ~26%** (566 estimado × 761 real); sem ferramentas erra ≤ 2% | medição de calibração, M7 | O template do modelo acrescenta ~180 tokens fixos de instrução de chamada e renderiza os schemas de outro jeito; o orçamento de 4 096 não é o que se acredita |
| O servidor oferece `POST /apply-template` (renderiza as mensagens com o template do modelo, incluindo `tools`) | teste direto no llama-server | Dá para contar exato: `/apply-template` → `/tokenize` |
| O modelo chutou `store.py` (arquivo inexistente) antes de listar o projeto; caso do Plan varia de 26 s a 43 s e 570+ tokens de saída | M5, M6 | Há ganho possível em orientar o modelo no workspace, mas 3 repetições não separam efeito de variância |
| O ciclo de 4–45 s não mostra nada até o fim; sem streaming não há TTFT | M5 | Percepção de lentidão e métrica faltando |
| Os 7 casos do M5 são minúsculos (1 arquivo, 6 linhas) | M5 | Não mede qualidade em tarefa real; nenhuma decisão de prompt/modelo tem lastro |
| `run_command` e servidores/hooks aprovados rodam com os privilégios do usuário; a política é lista de negação + aprovação | M4, M6 | `bwrap` está instalado na máquina-alvo; sandbox opcional é viável |
| Servidor rodando com 4 slots (sem `-np 1`) e sem `--alias` | M3/M5 | O `doctor` precisa avisar; efeito em memória nunca medido |

## Princípios

1. **Medir antes de mudar.** Nenhuma mudança de prompt, orçamento ou modelo entra sem passar pelo benchmark do M7.2 e pelo harness do M5 (21/21).
2. **Teste na camada que falhou.** Todo defeito corrigido ganha teste que falha no código antigo (já é a regra desde o M6).
3. **Tudo o que for novo é opt-in** e o custo de prompt ocioso continua medido (limite herdado: +10% do orçamento de entrada).
4. **Nada de recurso novo sem evidência** de que o núcleo está estável; M7.6, M7.7 e M7.8 são condicionais.

## Itens, na ordem de execução

### M7.1 — Testes de integração da TUI e `zc doctor` (primeiro)

- **Por quê:** a TUI aprova escrita e comando e nunca foi testada de ponta a ponta.
- **O quê:**
  - Suíte de integração que dirige a TUI com entrada simulada (`prompt_toolkit` pipe input + `DummyOutput`, e um teste por pseudo-terminal para o fluxo completo) cobrindo: aprovar/recusar/Esc/Enter/texto, `Ctrl+C` no turno e no prompt de aprovação, abertura com extensões, cada slash command, `/resume`, `/new`, retomada com extensões.
  - `zc doctor`: confere servidor (`/health`, `/props`), alias, **número de slots** (avisa se ≠ 1), `n_ctx` ≥ entrada + saída, `/tokenize` e `/apply-template`, `reasoning_effort` suportado, diretórios graváveis, config válida, hooks, MCP (sobe e lista o status), plugins. Cada falha traz a correção sugerida; saída ≠ 0 se algo bloqueia o uso.
- **Saída:** reintroduzir os dois defeitos do M1 faz a suíte falhar; `zc doctor` num servidor sem `-np 1` avisa; suíte roda em CI sem servidor (modelo simulado).

### M7.2 — Benchmark de tarefas reais pequenas (a régua do resto)

- **Por quê:** sem isso, M7.3–M7.7 são opinião.
- **O quê:** `scripts/m7_bench.py` com 12–15 tarefas em mini-repositórios gerados (nada baixado), cada uma verificada **executando os testes**: corrigir teste que falha, renomear em vários arquivos, adicionar função com teste, mudar assinatura e atualizar chamadores, localizar a origem de um erro, explicar um fluxo (verificação por fatos), recusar uma ação destrutiva pedida. Métricas: sucesso pass@1, rodadas, tokens, tempo, chamadas de ferramenta inválidas, aprovações pedidas. 5 repetições por tarefa (as 3 do M5 não separaram variância).
- **Saída:** baseline numérico do Ornith publicado em `docs/`, com intervalo (mediana e pior caso) e a taxa de variação entre repetições; script reproduzível contra qualquer `llama-server`.

### M7.3 — Contagem exata do prompt (`/apply-template` + `/tokenize`)

- **Por quê:** erro de −26% com ferramentas; o orçamento de entrada é o limite central do produto.
- **O quê:** `TokenCounter` passa a renderizar `messages + tools` com `/apply-template` e contar com `/tokenize` (com cache e **fallback** para o estimador atual, hoje inalterado), e o orçamento reserva o custo real do bloco de ferramentas. Calibrar a heurística de fallback com um fator medido para o caso com ferramentas. Reavaliar com dado se o orçamento de entrada de 4 096 deve mudar, já que o servidor tem janela de 8 192 e margem de VRAM de ~1 GB.
- **Saída:** erro ≤ 3% nas três classes medidas (curto/longo, com e sem ferramentas); `m5_eval` 21/21; o benchmark do M7.2 sem regressão. Qualquer mudança de orçamento só entra com A/B no M7.2.

### M7.4 — Streaming real e TTFT

- **Por quê:** turnos de até 45 s sem sinal; TTFT não medido; o M1 já permitia streaming real desde que não fosse simulado.
- **O quê:** `stream: true` (SSE) no `LlamaCppProvider`, montando texto e deltas de chamada de ferramenta; a TUI mostra o texto à medida que chega **depois** do estado de trabalho; o conteúdo de raciocínio nunca é exibido nem salvo (regra existente). `Ctrl+C` fecha o socket e confirma-se que o servidor parou de gerar. Fallback automático para o modo atual se o stream falhar. TTFT passa a entrar em `m5_eval` e nas métricas.
- **Riscos:** chamadas de ferramenta fragmentadas no stream e o marcador `<tool_call>` de fallback; contagem de tokens de saída. Mitigação: só emitir ao usuário texto fora de chamada de ferramenta e manter o caminho sem stream como padrão até o benchmark empatar.
- **Saída:** TTFT medido; benchmark e `m5_eval` sem regressão; cancelamento no meio do stream testado.

### M7.5 — Orientação do modelo no workspace (portão: o benchmark)

- **Hipótese:** um resumo compacto do projeto (árvore de até N entradas, ≲ 150 tokens, só quando o pedido cita arquivos ou o projeto é pequeno) reduz chutes de caminho e rodadas.
- **Regra:** a hipótese é **testada, não presumida**. Entra no prompt de produção só se, no benchmark (5 repetições), melhorar sucesso ou reduzir rodadas/erros de ferramenta de forma que supere a variância medida, com custo de prompt dentro do limite. Se não superar, o resultado negativo é registrado e o prompt de produção segue como está desde o M2.
- **Saída:** relatório A/B com intervalos e decisão explícita (adotar ou descartar).

### M7.6 — Sandbox opcional para comandos, hooks e servidores MCP (condicional à medição de uso)

- **Por quê:** o que o usuário aprova roda com os privilégios dele; `bwrap` já está na máquina-alvo.
- **O quê:** `command_policy.sandbox: bwrap` (desligado por padrão): raiz somente leitura, workspace gravável, `/tmp` privado, **sem rede** por padrão (liberável por comando/servidor), sem acesso ao `$HOME`. Aplicável a `run_command`, hooks e servidores MCP. Se `bwrap` faltar, mensagem clara e **nenhum fallback silencioso**.
- **Condição:** só avança se o benchmark (M7.2) mostrar que comandos continuam funcionando (testes, `python`, `git`) dentro do sandbox; senão fica documentado como limite conhecido.
- **Saída:** testes provando que um comando sandboxed não escreve fora do workspace nem alcança a rede; `m5_eval`/benchmark sem regressão com o sandbox ligado.

### M7.7 — Comparação de modelos e ajuste do servidor (condicional à decisão do usuário)

- **Pendência herdada do M5:** os candidatos (Qwen3-8B, Qwen3.5-9B, Gemma 4 12B, Qwen2.5-Coder-7B) nunca foram medidos no fluxo atual.
- **Condição:** `context.md` precisa ser atualizado pelo usuário para permitir outros modelos. Com isso, rodar `m5_eval` + benchmark por modelo, medir também o efeito de `-np 1`, do contexto de 16K e da margem de VRAM.
- **Saída:** tabela com mediana e pior caso por modelo/configuração e uma recomendação para a máquina-alvo, com as limitações declaradas.

### M7.8 — Compactação de histórico (condicional ao uso real)

- **Gatilho:** `/metrics` mostrando mais de **10% dos turnos** com `trimmed_messages > 0` em uso real (hoje nenhum caso do M5 chegou perto). Sem isso, não implementar.
- **Se acionado:** primeiro compactação **determinística** (remover saídas de ferramenta antigas, manter caminhos e decisões), só depois resumo por modelo; mesmo critério de medição no benchmark. Reavaliar o último recurso agressivo do `fit_messages`.

### M7.9 — Empacotamento e liberação

- Versão e `CHANGELOG`, instalação por `uv tool install`, `INSTALL.md` atualizado, CI que roda a suíte sem servidor (a suíte de integração do M7.1 usa modelo simulado), e checagem de que o pacote instalado enxerga `config/default.yaml` e `skills/` fora do diretório do repositório (hoje o carregamento usa o caminho relativo ao fonte).
- **Saída:** instalação limpa em um diretório novo roda `zc doctor` e um turno.

## Ordem e dependências

```
M7.1 (TUI + doctor) → M7.2 (benchmark) → M7.3 (tokens exatos) → M7.4 (streaming) → M7.5 (orientação)
                                   ↘ M7.6 (sandbox, condicional)        ↘ M7.9 (release)
M7.7 (modelos)  e  M7.8 (compactação): só quando suas condições forem satisfeitas
```

Cada etapa termina com: suíte verde, `m5_eval` 21/21, benchmark sem regressão (a partir do M7.2), `context.md` atualizado e revisão do usuário antes da etapa seguinte.

## Fora do escopo

- Novos recursos de extensão (HTTP/SSE para MCP, OAuth, plugins com código, subagentes paralelos).
- Mudança do modelo padrão sem decisão do usuário no `context.md`.
- Interface web ou editor. Os arquivos do Playwright (`e2e/`, `package.json`, `playwright.config.ts`) que estão sem commit no repositório não pertencem a este plano; se uma interface web for desejada, isso é um marco novo.
- Streaming simulado, cancelamento que descarte parte do estado da sessão, ou qualquer exibição de raciocínio privado.

## Riscos

| Risco | Mitigação |
|---|---|
| O benchmark pequeno vira régua enganosa (modelo "aprende" o teste) | Tarefas geradas com variação, 5 repetições, relatar intervalo e variância, nunca só média |
| Streaming quebra chamadas de ferramenta | Caminho sem stream permanece o padrão até empatar no benchmark; fallback automático |
| Contagem exata depende de `/apply-template` do servidor (versão do llama.cpp) | Fallback calibrado e teste que detecta a ausência do endpoint (o `doctor` avisa) |
| Sandbox atrapalha comandos legítimos | Opt-in, medido no benchmark, sem fallback silencioso |
| Testes de TUI frágeis | Priorizar entrada simulada (determinística); o teste por pseudo-terminal cobre só o essencial |

## Decisões que dependem do usuário

1. **Permitir outros modelos no `context.md`** (destrava o M7.7); hoje o Ornith é o único modelo de trabalho.
2. **Orçamento de entrada:** manter 4 096 até o M7.3 medir, ou já aumentar usando a janela de 8 192?
3. **Os arquivos do Playwright** sem commit (`.github/`, `e2e/`, `package.json`, `playwright.config.ts`): são seus? Se não forem, convém removê-los ou ignorá-los para não poluir o repositório.
