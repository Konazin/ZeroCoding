# ZeroCoding — contexto do projeto

Este arquivo dá contexto rápido a pessoas e agentes que trabalham no repositório. As decisões detalhadas de cada etapa ficam no [roadmap](docs/ROADMAP.md) e nos planos específicos em `docs/`.

## Objetivo

ZeroCoding é um coding agent local em terminal, inspirado nos fluxos de ferramentas de agentes como Claude Code, mas dimensionado para modelos menores e PCs leves ou intermediários. A prioridade é uso sério com contexto controlado, resposta ágil, segurança explícita e pouca infraestrutura.

Máquina de referência: Ryzen 5 4600G, 16 GB de RAM e AMD RX 5700 com 8 GB de VRAM.

## Modelo e runtime atuais

- Modelo de trabalho único: Ornith-1.5-9B Q5_K_M, GGUF denso/full model.
- Arquivo local neste ambiente: `/mnt/jogos/huggingFaceModels/Ornith-1.5-9B-Q5_K_M.gguf`.
- Runtime escolhido: `llama.cpp` `llama-server`, com Vulkan na RX 5700 (`Vulkan0`) e API local OpenAI-compatible.
- ZeroCoding usa alias `ornith-1.5-9b-q5-k-m` no endpoint `http://127.0.0.1:8080/v1`.
- Nesta etapa não há seleção, comparação ou configuração padrão de Gemma, Astra, Luna ou outros modelos. Os modos built-in reutilizam o mesmo Ornith e variam budgets.
- Perfil de coding documentado: temperature 0.6, top-p 0.95, top-k 20, presence penalty 0 e repetition penalty 1. O servidor usa contexto de 8192 e uma slot (`-np 1`) para uso individual. Os valores ficam no comando/configuração do servidor.
- O `llama-server` instalado foi 0.6.0 (build b11429). Seu endpoint `/props` declara `supports_tools: true`, `supports_reasoning_effort: false` e `supports_preserve_reasoning: false` para o template carregado. ZeroCoding encaminha `reasoning_effort`, mas isso não está validado como controle nativo para o Ornith; effort deve ser entendido pelos budgets locais até uma validação futura.
- Smoke local na RX 5700/Vulkan observou aproximadamente 7.05–7.18 GB de VRAM usada (8.57 GB totais), processamento de prompt em 112–123 tokens/s e geração em 17.8–18.9 tokens/s em requests curtas. São observações do smoke, não um benchmark estável. A contagem exata de camadas offloaded não foi confirmada.

## Arquitetura e contratos

- `providers/ollama.py` é legado: mantido só por compatibilidade de configs antigas, sem novas funcionalidades e sem validação contra um servidor Ollama real. O runtime suportado é llama.cpp.
- Runtime principal em Python; TUI de produção em Rich + prompt_toolkit.
- `core/agent.py` monta contexto limitado, chama o provider e executa um loop limitado de ferramentas.
- Providers normalizam texto, tool calls, uso de tokens e dados de reasoning. Raciocínio privado nunca deve aparecer na TUI nem ser salvo em histórico de sessão.
- Leitura, listagem e busca são limitadas ao workspace. Escritas e shell mostram preview e exigem aprovação explícita.
- Plan mode expõe e executa somente ferramentas de leitura; a proteção também existe no executor.
- Preferir dependências pequenas e interfaces testáveis. Evitar frameworks ou subprocessos de modelo dentro do Python quando o servidor local separado resolve o problema.

## Estado do roadmap

- **M3, M4, M5 (só Ornith) e M6 concluídos em 2026-10-16** (detalhes abaixo). O mega teste M7.2–M7.4 foi executado contra o Ornith em 2026-10-16; os critérios de benchmark, precisão do fallback e qualidade/latência do streaming não passaram. M8 está implementado e a suíte automatizada local está verde; a CI ainda precisa confirmar a instalação empacotada. O briefing e os relatórios estão em `docs/MEGA-TEST-M7-M8-2026-10-16.md`. Ver também `docs/ROADMAP-m7.md`, `docs/IMPLEMENTATION-PLAN-m7.md` e `docs/ROADMAP-m8.md`.

- M1 visual/fluxo foi concluído e revisado pelo usuário.
- M2, sobre prompt/contexto, foi declarado concluído pelo usuário em 2026-10-14. Os relatórios em `docs/` ficam como referência; o prompt de produção segue inalterado até uma decisão explícita.
- M3 está liberado, mas só deve começar quando o usuário pedir. Ver `docs/ROADMAP-extension.md` para os itens de revisão e sub-marcos adicionais.

### M2.5 — base estável (concluído em 2026-10-16)

- Grupo `dev` (pytest) em `pyproject.toml`/`uv.lock`; `uv run pytest -q` e `unittest` passam 81 testes em ambiente limpo.
- `test_qwen35_study` agora garante um `python` no PATH do teste (sistemas só com `python3`).
- Trabalho segue na branch `development`, sincronizada com `origin/main`.

### M3 em andamento (iniciado em 2026-10-16)

- 1.1 limpeza feita: removidos o pacote morto `src/zerocoding/tools/` e `tui/widgets.py` vazio; `ToolRegistry` mantém só `approve`. Os protótipos `tui/demo*.py`/`textual_app.py` continuam em `src/` (mover para `scripts/` exige ajustar README, CLAUDE.md e `scripts/measure_m1_ui.py`; decisão pendente).
- 1.2 estimativa real de tokens: `core/tokens.py` (`TokenCounter`) usa `/apply-template` + `/tokenize` via `LlamaCppProvider.count_prompt`, com cache e fallback heurístico após falha. O mega teste confirmou os endpoints; o fallback errou de 7,3% a 31,0% por classe e precisa de calibração. `fit_messages` recebe o contador; detalhes em `docs/MEGA-TEST-M7-M8-2026-10-16.md`.
- 1.3 decomposição: `core/agent.py` (loop em métodos `_chat`, `_chat_non_empty`, `_run_tool_call`) + `core/budget.py` (`fit_messages`) + `core/toolcalls.py` (marcador compacto, eventos, resumos); `cli.py` ficou só com `main` e os handlers de slash commands foram para `commands.py`. Correção embutida: o `fit_messages` pós-rodada de ferramentas passou a usar o contador de tokens configurado. O retry de resposta vazia (item 1.4) ficou consolidado em `_chat_non_empty`.
- 1.5 effort: decisão registrada: effort = budgets locais (tokens de saída/rodadas). O `reasoning_effort` ainda é enviado ao llama.cpp, mas o Ornith declara `supports_reasoning_effort: false`; o `/status` agora rotula "Effort (budgets)" e descreve o campo nativo como não validado.
- Medições contra o llama-server real (2026-10-16; Ornith, janela 8192; configuração observada antes do mega teste: alias = caminho do GGUF e 4 slots, sem `--alias`/`-np 1`; no mega teste: alias explícito e 1 slot):
  - `/tokenize` responde `{"tokens":[...]}` no formato esperado e o `TokenCounter` funciona de ponta a ponta. Erro da heurística de ~4 chars/token (JSON) vs. real: Python +14%, português +2%, inglês −4%, schemas de ferramentas +11%, YAML pequeno −29%. Em geral dentro de ±15%; a contagem real vale sobretudo perto do limite.
  - Smoke do agente (resposta direta, leitura com ferramenta, Plan bloqueando escrita, escrita recusada sem criar arquivo): tudo certo, sem resposta vazia em 4 execuções, então o item 1.4 não foi reproduzido com o Ornith (o problema documentado era do Qwen3.5).
  - A/B de `dynamic_context` (`scripts/dynamic_context_ab.py`, 8 casos × 1 repetição): economiza ~115 tokens de ~660 no prompt (~17%) e acertou 5/8 contra 7/8 com ele desligado. A amostra é pequena e ruidosa, mas não há evidência a favor: `dynamic_context` continua desligado por padrão.

### M4 — fluxo confiável (implementado em 2026-10-16)

- `edit_file` (path, old_text, new_text): `old_text` precisa casar exatamente uma vez; mostra diff e exige aprovação; bloqueado no Plan. `write_file` continua para arquivos novos/reescrita.
- `core/command_policy.py` + bloco `command_policy` no YAML: executáveis negados (sudo, dd, mkfs…) e `allow` opcional, `rm` recursivo só dentro do projeto e nunca na raiz, ambiente mínimo (PATH, HOME, LANG… + `env_passthrough`), timeout e limite de saída configuráveis. Comando bloqueado nem chega ao prompt de aprovação. A aprovação continua obrigatória.
- Erros legíveis: argumentos ausentes, ferramenta desconhecida (lista as disponíveis), inteiros/regex inválidos, timeout, binário inexistente, limite de rodadas com instrução de próximo passo.
- Testes: `tests/test_m4_workflow.py` (aprovação/recusa de diff e comando, symlink e caminhos fora do workspace, política, erros, limite de rodadas, falha do provider, isolamento de sessão e ciclo busca → leitura → edição recusada → edição aprovada com provider simulado). Smoke real com o Ornith: edição mínima aplicada com diff mostrado antes da aprovação.

### M6 — extensibilidade (implementado em 2026-10-16; tudo opt-in e desligado por padrão)

- Pré-requisitos: cancelamento (Ctrl+C / `CancelToken`) e métricas locais por turno (`/metrics`, `.zerocoding/metrics/turns.jsonl`, só números).
- M6.1 hooks (`core/hooks.py`), M6.2 MCP stdio (`mcp/`, allowlist + tetos de tokens, saída rotulada como dado externo), M6.3 subagente `explore` somente leitura (`core/subagent.py`), M6.4 plugins declarativos (`core/plugins.py`, nenhum Python executado), ligados por `core/bootstrap.py`. Config e exemplos em `config/default.yaml`; resultados em `docs/ROADMAP-m6.md`.
- Medido: +228 tokens por chamada com MCP+explore ociosos (limite do plano: ~410); `scripts/m5_eval.py --extensions` 21/21, 0 erros em 40 chamadas.
- Corrigido (vinha do M1): a aprovação na TUI falhava sempre (teclas `s-y`/`s-n` inválidas) e aceitava qualquer texto + Enter como "sim". Só `Y` aprova agora; `tests/test_tui_confirm.py`.
- Decisão: o subagente foi implementado mesmo sem o gatilho de uso real do plano; segue desligado.

### M7 — confiabilidade, medição e empacotamento (encerrado em 2026-10-17, versão 0.2.0)

- Fechamento: M7.9 validado localmente (wheel em venv limpo; CI do GitHub é a confirmação final). M7.5 não adotado por falta de margem no benchmark; M7.6–M7.8 ficam condicionais (ver `docs/ROADMAP-m7.md`). Smoke test da TUI com streaming real adiado por decisão do usuário.

- Rodada final: 74/75 (98,7%) sem streaming e 75/75 com streaming; as medições anteriores (85%) refletiam defeitos do verificador (ver `docs/ROADMAP-m7.md`). Fallback de tokens recalibrado (mediana 6%, p90 12%); meta de 3% substituída por mediana ≤ 10% e p90 ≤ 20% (aprovada em 2026-10-17). Streaming devolve `usage` e está ligado por padrão desde 2026-10-17; riscos em observação até o smoke test da TUI. Mascote Patinhas (`tui/mascot.py`) substitui o fantasma.

- `search_files` ignora links simbólicos, corrigindo leitura de arquivos fora do workspace; `write_file` e `edit_file` revalidam caminho e snapshot após aprovação, gravam por substituição atômica e recusam diff obsoleto.
- `run_command` e hooks agora drenam saída de subprocesso com captura limitada; cancelamento por timeout encerra o grupo do processo em POSIX. A confirmação sem `prompt_toolkit` aceita somente `Y`, igual à TUI principal.
- Novo `zc doctor`: configurações, diretórios, skills, hooks, plugins, MCP, saúde do llama-server, `/props`, slots, contexto, `/tokenize`, `/apply-template` e suporte a effort. A execução não envia prompt de geração.
- M7.1: integração TUI→agente→escrita aprovada/recusada, aprovação por Y/Esc/Enter/texto/Ctrl+C, cancelamento no turno, ciclo PTY, comandos de sessão e preservação de extensão em `/new` e `/resume`; `zc doctor` usa endpoints e MCP simulados. Workflow Python em `.github/workflows/python-tests.yml`.
- M7.2: `scripts/m7_bench.py` contém 15 tarefas com verificadores independentes e cinco repetições. Após corrigir o falso negativo do verificador de `change_signature` e repetir esse caso, o agregado é 64/75 sem streaming e 65/75 com streaming; `change_signature` passou 5/5 e `run_tests` falhou 0/5. Chamadas inválidas: 2 sem streaming, 6 com streaming. O relatório do mega teste explica a reconciliação.
- M7.3: `/apply-template` + `/tokenize` contam o prompt real e os schemas; o fallback permanece impreciso. Com amostra variada, o erro máximo por classe ficou entre 7,3% e 31%, acima da meta de 3%. O limite de entrada continua 4.096; `fit_messages` preserva pares de tool call/result e o pedido atual.
- M7.4: SSE e cancelamento foram medidos no servidor. O cancelamento fechou a resposta e deixou o slot ocioso; o primeiro texto levou 25,7 s. M5 passou 21/21 nos dois modos, mas streaming teve 2 erros de ferramenta e TTFT mediano 6,35 s (pior 83,36 s). Tokens de streaming não vieram em `usage`; `streaming_enabled` continua falso.
- M7.9: `config/default.yaml` e `skills/` são incluídos como recursos do pacote; carregadores usam `importlib.resources`; `INSTALL.md` atualizado. Workflow Python agora instala o projeto sem modo editável, confere os comandos instalados e executa a suíte contra o pacote instalado. Teste local copia o pacote para caminho isolado; `setuptools` está ausente neste ambiente, então o wheel não foi construído aqui e a CI ainda precisa confirmar a instalação. Versão de release ainda não definida.
- Validação automatizada (M7 + M8): `239 passed, 10 subtests passed`; `git diff --check`, `compileall` e os comandos de ajuda instalados passaram. Os benchmarks separados geraram respostas com o modelo local. O M7.5 não avançou porque M7.2–M7.4 não passaram; M7.6–M7.8 seguem condicionais. A CI ainda precisa confirmar a instalação empacotada não editável; `setuptools`/`wheel` faltam no ambiente local.

### M8 — integridade e privacidade das sessões locais (implementado e validado localmente)

- M8.1–M8.4 implementados: diretório/arquivos privados em POSIX, escrita atômica, limpeza de temporários antigos, persistência opcional, listagem só de metadados, remoção confirmada e documentação de privacidade. M8.2 valida payloads, preserva datas legadas por `mtime` sem reescrita e mantém a sessão atual em retomadas sem ID, inexistentes, inválidas ou cuja preparação do provider falhe.
- `/sessions` avisa sobre arquivos inválidos pelo ID sem exibir conteúdo; `/sessions delete <id>` permite removê-los. `--no-session-save` e `session_persistence: false` mantêm a sessão atual apenas em memória.
- Auditoria final corrigiu rejeição de payload malformado antes da substituição, falha de `/new` sem descartar o estado atual, atualização do workspace de ferramentas ao iniciar sessão e gravação dupla na inicialização.
- Suíte local completa passou: 239 testes e 10 subtestes. A confirmação da instalação não editável pela CI segue pendente; o ambiente local não tem `setuptools` nem `wheel` para validar o artefato aqui.

### M5 — avaliação (executada em 2026-10-16 só para o Ornith)

- `scripts/m5_eval.py` (7 casos × 3 repetições, workspace temporário, aprovação programática): 21/21 concluídos, 35 chamadas de ferramenta com 2 erros, ~22 tokens/s, RSS ~5,0 GB, VRAM da GPU 7,6 de 8,57 GB. Relatório em `docs/model-evaluation.md`, dados em `docs/m5-ornith-1.5-9b-q5_k_m-results.json`.
- Comparação com Qwen3-8B, Qwen3.5-9B, Gemma 4 12B e Qwen2.5-Coder-7B **não feita**: o Ornith segue como modelo único. Para comparar, atualizar este arquivo e rodar o harness com `--label` por modelo.
- Limitações: sem TTFT real (sem streaming; `prompt_ms` sofre efeito do cache), VRAM é da GPU inteira, 2 erros de ferramenta sem causa confirmada.

### Preparação do M3 (encerrada em 2026-10-14; M3 não iniciado)

- Baseline: tags locais `m3-baseline` (M2 concluído) e `m3-baseline-2` (após as ressalvas abaixo); `development` sincronizada com `origin/development`, que preserva a linha antiga `9658fd2` apenas no histórico.
- Suíte: `uv run python -m unittest discover -s tests -p 'test_*.py'` com 81 testes passando.
- Ressalvas tratadas: contexto dinâmico opcional (`dynamic_context`, desligado por padrão, não medido); testes de caracterização dos comandos do `cli.py`; `providers/ollama.py` marcado como legado.
- `dynamic_context` medido (ver M3 em andamento): continua desligado.

## Regras de trabalho

- Trabalhar na branch `development` salvo orientação diferente.
- Preservar alterações locais existentes; nunca descartá-las para limpar o working tree.
- Usar workspace temporário para testes de ferramentas com escrita ou comando e verificar aprovação/Plan.
- Atualizar este arquivo quando uma decisão estrutural mudar, mantendo o roadmap e os relatórios como fontes específicas de cada etapa.
