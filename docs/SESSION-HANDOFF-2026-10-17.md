# Handoff da sessão — 2026-10-17

Branch `development`, tudo enviado com push. 321 testes passando. O servidor `llama-server` fica desligado entre sessões (iniciar com o comando do README).

## O que mudou nesta sessão

- **M7 encerrado (0.2.0):** benchmark 74/75 sem streaming e 75/75 com streaming depois de corrigir os verificadores; fallback de tokens recalibrado (mediana 6%, p90 12%; meta aprovada: mediana ≤ 10% e p90 ≤ 20%); streaming ligado por padrão; pacote validado em ambiente limpo. Ver `ROADMAP-m7.md` e `CHANGELOG.md`.
- **TUI em tela cheia** (`fullscreen: true`): janela fixa, histórico rolável (PageUp/PageDown, roda do mouse), caixa de digitação sempre visível (Enter não envia enquanto há tarefa; Ctrl+C cancela), mascote Patinhas animado no topo ao clicar, atividade e tokens por tarefa, diff no estilo Claude Code, Y/N preso ao prompt, Ctrl+T expande diffs.
- **Configuração interativa:** `/config` (abas Status, Config, Providers), `/model`, `/provider` e o assistente de provedor com escolhas controladas.
- **`/permission`:** ask, auto (packs de comandos avaliados por código em `core/command_packs.py`) e yolo, só na sessão.
- **Agente:** comandos impressos como bloco ```bash viram `run_command` com aprovação (`shell_block_fallback`).

## Pendências para a próxima sessão (memória do assistente: `effort-redesign-pending`)

1. **Redesenho do effort** (`RESEARCH-effort.md`). Decisão: o nível depende da folga de contexto até o auto-compact; sem tecla "parar de pensar". Falta: implementar `reasoning_budget_tokens` por requisição, `max_tokens` = raciocínio + resposta, adaptativo por etapa, rodadas de ferramenta fora do effort (limite alto com aviso ou "continuar" automático), calibração no benchmark do M7, e o equivalente para Ollama (`reasoning_effort`).
2. **Compactação de histórico** (M7.8): pré-requisito do item anterior; hoje `fit_messages` só descarta mensagens.
3. **Smoke test da TUI com o modelo real** (Ornith e Qwen 3.5 4B no Ollama): ordem do texto antes das ferramentas, animação, terminais estreitos.
4. **Benchmark mais difícil** (tarefas maiores, vários arquivos): as 15 atuais saturaram; é também o gatilho para reabrir o M7.5.
5. **CI:** conferir na aba Actions do GitHub se o workflow `python-tests.yml` passou com o pacote não editável (M7.9).
6. **Arquivos do Playwright** (`.github/workflows/playwright.yml`, `e2e/`, `package*.json`, `playwright.config.ts`) seguem sem commit, fora de qualquer plano.
7. Qwen 4B só descreve em vez de usar `write_file`: avaliar prompt específico para modelos pequenos ou aceitar o limite.

## Como reproduzir os testes reais da TUI

Os scripts de terminal real usados nesta sessão não estão versionados; o teste `tests/test_fullscreen.py::TestFullscreenEndToEnd` cobre o fluxo escrever, aprovar e manter a entrada durante o trabalho com um servidor de modelo falso.
