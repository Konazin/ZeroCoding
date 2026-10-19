# Changelog

## Unreleased (M10: verification loop)

- After the agent edits files, the project's own checks run and failures go back to the model (up to 2 fix rounds); `/verify` controls it per session. Detected commands are approved once; configured ones are trusted.
- `m7_bench.py --verify`. Not yet measured against a model.
- Project instructions file (`ZEROCODING.md`, `AGENTS.md` or `CLAUDE.md` in the workspace root) added to the system prompt, capped at 2,000 characters; `/instructions`.

## Unreleased (M9: git, undo and modular providers)

- Git tools, only inside a repository: `git` (status, diff, log; read-only, allowed in Plan mode, hardened against repository-controlled code) and `git_commit` (explicit paths, approved message, hooks run, never auto-approved).
- `/undo`: per-turn journal of files written by `write_file` and `edit_file`; conflict-safe, private, works without git.
- yolo and auto still ask for network, install and history-rewriting commands (`git push`, `curl`, `pip install`, ...) and for every commit.
- Providers declare capabilities (`zc doctor` shows them), report `finish_reason` and reasoning tokens, and empty replies explain their cause.
- Context-window probes for generic OpenAI-compatible servers, LM Studio and native Ollama; a startup warning when the window cannot be detected.
- `providers.<name>.thinking: auto | on | off | budget:N`.
- Test kit with fake llama.cpp, OpenAI-compatible and Ollama servers; `m7_bench.py --provider-type/--thinking`; hard suite grows to 11 tasks (three on git).
- Not yet measured against a model: benchmark gates for the M9 closing (see `docs/ROADMAP-m9.md`), so the version stays 0.2.0.

## 0.2.0 — 2026-10-17 (fecha o M7)

- Novo mascote Patinhas: anda no lugar enquanto o agente trabalha; o texto que precede uma chamada de ferramenta permanece na tela.
- Streaming ligado por padrão (`streaming_enabled: false` desliga). Devolve `usage`, e argumentos de ferramenta truncados refazem o turno sem streaming.
- Fallback de contagem de tokens recalibrado (erro mediano 6%, p90 12%); a contagem exata do servidor continua sendo o caminho normal.
- Benchmark M7.2 reconciliado: 74/75 sem streaming e 75/75 com streaming. Os verificadores de `run_tests`, `direct_fact` e `destructive_request` foram corrigidos; o harness grava `approval_log` e `answer_excerpt`.
- Pacote: `config/default.yaml` e `skills/` incluídos como recursos; wheel construído e instalado em ambiente limpo com `zc`, `zerocoding` e `zc doctor` funcionando fora do checkout.
- Sessões locais privadas e atômicas (M8).

## 0.1.0

- Primeira versão: TUI, agente com ferramentas, extensões opt-in (M1–M6).
