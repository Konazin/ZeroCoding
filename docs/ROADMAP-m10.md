# M10 — Um agente que verifica o próprio trabalho

**Estado (2026-10-18, branch `m10-verification`, a partir de `development` com o M9):** implementado e testado sem modelo (463 testes). Nada disto foi medido contra um modelo; os gates abaixo continuam abertos.

Por quê: o Qwen 4B corrigiu bugs sem rodar os testes e errou (`h_root_cause_dependency`, `h_two_bugs_two_modules`, ver `BENCH-HARD.md`). Um agente de código de verdade confere o que fez, tem as convenções do projeto à mão e roda sem uma pessoa na frente.

| Etapa | O que faz | Onde |
|---|---|---|
| M10.1 Laço de verificação | Depois de `write_file`/`edit_file`, o código roda o comando de verificação (configurado ou detectado), devolve a saída aparada ao modelo e deixa até `max_attempts` rodadas de correção. Se continuar falhando, a resposta termina com "Not verified". `/verify` controla a sessão. | `core/verify.py`, `core/agent.py`, `core/tools.py` (`run_verification`) |
| M10.2 Instruções do projeto | `ZEROCODING.md`, `AGENTS.md` ou `CLAUDE.md` na raiz entram no prompt de sistema (teto de 2.000 caracteres). Sem arquivo, o prompt não muda. Não altera aprovações. | `core/instructions.py` |
| M10.3 Modo headless | `zc run -m "tarefa"`: somente leitura por padrão, `--write`, `--commands auto`, `--json`, códigos de saída (2 = não verificado). Commit, rede e instalações nunca são aprovados. | `core/headless.py`, `cli.py` |

## Decisões de desenho

- **O código decide quando verificar, não o modelo.** Modelo pequeno diz "pronto" sem rodar nada.
- **Comando detectado pede aprovação uma vez; comando configurado é confiável** (como um hook). Recusar desliga a verificação na sessão.
- **Falhas voltam como mensagem de usuário** (`Verification failed: ...`), sem inventar uma chamada de ferramenta que o modelo não fez. Um comando que não consegue rodar (bloqueado pela política, inexistente) é relatado, não reenviado ao modelo.
- **`max_attempts` conta rodadas de correção**: até três execuções por pedido com o padrão 2; nenhuma chamada ao modelo é gasta depois da última falha.
- **Headless não tem humano**: as permissões vêm só de flags, o padrão é leitura.

## Gates abertos (precisam de modelo)

1. `m7_bench.py --suite hard --verify` contra a mesma suíte sem `--verify`: o ganho nas tarefas de causa raiz e de dois bugs é a prova de que o laço vale o tempo extra.
2. Custo do laço: execuções extras e tokens por tarefa (o benchmark já registra `llm_calls`, `prompt_tokens` e as novas métricas `verify_runs` e `verify_failures`).
3. Custo de prompt das instruções do projeto: até ~500 tokens por chamada quando o arquivo existe.
4. O benchmark pequeno não pode regredir (o laço só age em tarefas com comando de teste).

## Limites conhecidos

- A verificação só enxerga edições de `write_file` e `edit_file`; mudanças por `run_command` ou `git_commit` não disparam.
- Um comando de verificação lento (testes de minutos) trava o laço até o `timeout` (120 s por padrão).
- O comando é um só (o primeiro); vários comandos ficam para depois.
- Pytest é detectado por arquivos de configuração e nomes `test_*.py`; projetos com outra convenção precisam de `verify.commands`.
- O arquivo de instruções de um repositório clonado entra no prompt automaticamente (só texto, as aprovações continuam valendo); `instructions.enabled: false` desliga.
