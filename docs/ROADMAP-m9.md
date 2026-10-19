# M9 — Git nativo, desfazer e providers modulares

**Estado (2026-10-18):** implementação concluída e testada sem modelo (416 testes). **Gates de benchmark pendentes**: a máquina não comportou o Ornith (VRAM e RAM ocupadas), então M9.0 e o fechamento M9.8 não rodaram. A versão fica 0.2.0 até lá.

Decisões tomadas (recomendadas no plano e aceitas ao pedir a implementação): Ollama pelo provider nativo, diário de arquivos antes de qualquer snapshot do git, `git_commit` incluído.

## Entregas

| Etapa | Estado | Onde |
|---|---|---|
| M9.0 Linha de base no Ornith | **pendente** (precisa do servidor) | `scripts/m9_baseline.sh` pronto, com checagem de servidor e RAM |
| M9.1 Git só de leitura | feito | `core/git_tools.py`, ferramenta `git` em `core/tools.py` |
| M9.2 Diário e `/undo` | feito | `core/journal.py`, `commands.py` (`/undo`) |
| M9.3 Commit assistido e rede sob aprovação | feito | `git_commit`, `core/command_packs.py` (`needs_explicit_approval`), `core/permissions.py` |
| M9.4 Capacidades e diagnóstico de parada | feito | `providers/base.py`, `core/agent.py` (`_stop_cause`), `core/doctor.py` |
| M9.5 Janela por sonda | feito | `providers/openai_compatible.py`, `providers/ollama.py`, aviso em `cli.py` |
| M9.6 Raciocínio por provider e kit de conformidade | feito | `thinking` em `core/config.py`, `tests/provider_kit.py`, `tests/test_provider_conformance.py`, `m7_bench.py --provider-type/--thinking` |
| M9.7 Snapshots para efeitos de comando | **não acionado** | só entra se o diário deixar uma lacuna medida |
| M9.8 Fechamento | **parcial**: docs e testes; faltam os gates com modelo | abaixo |

## Gates de fechamento ainda por medir (precisam do Ornith)

1. Harness M5 21/21 e benchmark pequeno sem regressão (linha de base do M9.0).
2. Suíte difícil igual ou acima da linha de base; os casos `h_git_*` são novos e entram no baseline.
3. Custo ocioso dos schemas `git` e `git_commit`: estimado abaixo de 200 tokens com o contador heurístico (teste `test_idle_schema_cost_of_the_git_tools_stays_small`); falta medir com `/apply-template`.
4. Efeito de `thinking: off` na qualidade: nunca medido; por isso o padrão continua `auto`.

## Segurança do git (requisitos do plano)

- Leituras: `--no-pager --no-optional-locks`, `core.fsmonitor=false`, `core.hooksPath=/dev/null`, `--no-ext-diff --no-textconv`, ambiente mínimo, sem `-c` vindo do modelo. Testes plantam fsmonitor, pager, external diff e textconv e provam que nada executa.
- Commit: só caminhos explícitos, `--only`, os hooks do repositório rodam (por isso nunca é aprovado sozinho), sem `--no-verify`, nada de push, reset, clean ou checkout por ferramenta.
- Desfazer nunca sobrescreve arquivo alterado depois da escrita do agente.

## Limites conhecidos

- O diário não cobre alterações feitas por `run_command` (aviso mostrado no `/undo`).
- Os dados do diário são conteúdo de arquivos em texto simples, protegidos só por permissões do sistema.
- O provider nativo do Ollama não faz streaming; a sonda de janela dele usa `/api/show` e é um teto de 8192, não uma medida do que está carregado. A sonda do LM Studio segue a documentação e não foi testada contra um servidor real.
- `thinking: budget:N` só existe no llama.cpp; nos outros tipos é tratado como "on" ou ignorado, e o `zc doctor` avisa.
