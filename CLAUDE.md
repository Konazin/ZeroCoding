# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

ZeroCoding is a local terminal coding agent (Python ≥3.10, package `zerocoding`, entry points `zerocoding` / `zc`) sized for small local models on modest hardware (reference: Ryzen 5 4600G, 16 GB RAM, RX 5700 8 GB). The single working model is Ornith-1.5-9B Q5_K_M served by a separate `llama-server` (llama.cpp, Vulkan) at `http://127.0.0.1:8080/v1`, alias `ornith-1.5-9b-q5-k-m`. See `context.md` for current decisions and `docs/ROADMAP.md` (plus `docs/ROADMAP-extension.md`) for milestones. Docs, README and UI text mix Portuguese (docs) and English (visible UI text).

## Commands

```bash
uv sync --locked                      # install from uv.lock into .venv
uv run zc                             # interactive TUI
uv run zc -m "prompt"                 # one-shot; no tools, cannot execute changes
uv run python -m unittest discover -s tests -p 'test_*.py'   # full suite (unittest is the reference runner)
uv run pytest -q                      # same suite via pytest (dev dependency group; `uv sync` installs it)
uv run python -m unittest tests.test_agent_tools.<Class>.<test>   # single test
uv run python -m py_compile src/zerocoding/**/*.py
uv sync --locked --extra prototype && uv run python -m zerocoding.tui.demo textual   # optional Textual prototype
```

The llama.cpp server must be started separately (launch command in README); `/provider test` in the TUI checks it. Its `-c` must be ≥ input + output budgets (default 4096 + 1024; example uses 8192).

## Architecture

- **`core/agent.py`** is the center. `Agent.ask` builds messages (`core/prompt.py`), trims them with `fit_messages` against `max_input_tokens` (estimate: ~4 chars/token, reserving tool-schema cost), calls the provider, and runs a bounded tool-call loop. It falls back to a `<tool_call>{...}</tool_call>` text marker when native tools are unavailable, retries once on an empty response, and emits `AgentEvent`s (`core/events.py`) for the TUI. Session controls (Plan, Ultrathink, Effort low/medium/high) change output-token and tool-round budgets via `effective_budgets` (rounds capped at 12).
- **`core/tools.py`** `ToolRegistry` is workspace-scoped (rejects paths outside the root and in ignored dirs). `list_files`/`search_files`/`read_file` are read-only; `write_file`, `edit_file` (exact single-match replace) and `run_command` always go through the injected `approve` callback with a diff/command preview; `run_command` is also filtered by `core/command_policy.py` (deny/allow, minimal env, timeout, output cap) before the prompt. Plan mode is enforced twice: read-only schemas are exposed, and the executor blocks non-read tools.
- **`providers/`**: `base.py` defines the provider interface and `normalize_turn` → `ProviderTurn`/`ToolCall`; `llama_cpp.py` and `openai_compatible.py` adapt the supported backends; `ollama.py` is legacy (kept for old configs, no new features, not validated against a real server). Providers may declare `native_effort_kwargs`; effort is only sent natively when declared (Ornith's template does not support it, so effort is budget-only). Private reasoning content must never be shown in the TUI or saved in session history.
- **`core/config.py` / `router.py`**: layered config (`config/default.yaml` → `~/.zerocoding/config.yaml` → env/`.env`); legacy `max_output_tokens`/`max_tool_rounds` feed the Medium profile unless `effort_profiles` is set. `router.build_session_provider` builds a provider per session.
- **`core/sessions.py`**: JSON sessions in `~/.zerocoding/sessions` storing provider/model/mode, Plan/Ultra/Effort, skills, history and context files. Each session's prompt contains only its own history; legacy SQLite memory (`memory/sqlite.py`) is never injected.
- **`core/project_context.py`**: files enter prompts only via explicit `/context add` / `/read`; nothing is auto-read.
- **`tui/app.py`**: production TUI (Rich + prompt_toolkit, scrollback-based). `tui/demo*.py`, `textual_app.py` are prototypes; Textual is an optional extra.
- **`scripts/` and `docs/*-study*`**: M2 prompt/effort/model studies. Raw responses go to `.zerocoding/studies/m2/` (not versioned); only aggregated metrics are committed.

## Working rules (from context.md)

- Work on branch `development` unless told otherwise; preserve existing uncommitted local changes, never discard them to clean the tree.
- Do not start M3 until the user explicitly declares M2 concluded; keep the production prompt unchanged for now.
- Test anything with writes or commands in a temporary workspace and verify approval and Plan-mode behavior.
- Prefer small dependencies and testable interfaces; avoid in-process model runtimes (the separate local server is the design).
- Update `context.md` when a structural decision changes.
