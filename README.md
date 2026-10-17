# ZeroCoding

ZeroCoding is an open source terminal coding assistant built in Python. It is inspired by the general experience of modern coding agents in the terminal, but uses its own identity, interface text, provider layer and ghost ASCII logo.

The MVP focuses on a compact coding-agent loop for local and OpenAI-compatible models. It keeps each conversation in its own session, sizes the prompt from the server context window (4,096 estimated tokens when it cannot be detected), reserves 1,024 tokens for output, and supports structured tool calls. In the TUI, reading and searching are available to the agent; file writes and shell commands always show a preview and require approval.

## Install

```bash
uv sync --locked
```

This creates `.venv` and installs the versions recorded in `uv.lock`. Run project commands with `uv run` so they use that environment:

```bash
uv run zerocoding
uv run zc
```

Use `uv add <package>` or `uv remove <package>` to change runtime dependencies; commit both `pyproject.toml` and `uv.lock`.

Send a one-shot prompt:

```bash
uv run zc -m "Explique este projeto em poucas linhas"
```

Check the provider, server settings and configured extensions without generating a model response:

```bash
uv run zc doctor
```

## M1 UI prototypes

To compare the Rich + prompt_toolkit scrollback prototype with the persistent Textual prototype, follow the shared scenarios in [the stack comparison guide](docs/m1-stack-comparison.md):

```bash
uv run python -m zerocoding.tui.demo rich
```

Textual is optional and is not installed for the production TUI. To run its prototype, install the extra first:

```bash
uv sync --locked --extra prototype
uv run python -m zerocoding.tui.demo textual
```

## Local Ornith with llama.cpp

The default model is the local Ornith-1.5-9B Q5_K_M GGUF served through llama.cpp. The default endpoint is `http://127.0.0.1:8080/v1`; start the model server before ZeroCoding.

### Build llama.cpp with Vulkan

If `llama-server` is already installed with Vulkan support, skip the build and check its devices:

```bash
llama-server --list-devices
```

On Linux, install the Vulkan development files, `glslc`, SPIR-V headers, CMake, and a C++ compiler. Check that the Vulkan driver is visible with `vulkaninfo`, then build:

```bash
git clone https://github.com/ggml-org/llama.cpp
cd llama.cpp
cmake -B build -DGGML_VULKAN=ON
cmake --build build --config Release -j
```

On NixOS, the same tools can be provided temporarily in a shell:

```bash
nix-shell -p cmake gcc git vulkan-loader vulkan-headers shaderc spirv-headers vulkan-tools
vulkaninfo --summary
```

Make sure the system's AMD Vulkan driver is enabled. The official llama.cpp build guide has platform-specific dependency notes and Vulkan checks: [llama.cpp Vulkan build guide](https://github.com/ggml-org/llama.cpp/blob/master/docs/build.md#vulkan).

### Start Ornith

Adjust `MODEL` if the GGUF is stored elsewhere. `Vulkan0` selects the RX 5700 on the reference machine. Start with all layers requested; if the server reports an allocation failure, lower `-ngl` until it starts. `-c 8192` leaves room above ZeroCoding's default 5,120-token input-plus-output budget while keeping the active context bounded. `-np 1` keeps one server slot for this single-user CLI instead of allocating parallel slots automatically.

```bash
MODEL=/mnt/jogos/huggingFaceModels/Ornith-1.5-9B-Q5_K_M.gguf
llama-server \
  --model "$MODEL" \
  --host 127.0.0.1 --port 8080 \
  --alias ornith-1.5-9b-q5-k-m \
  --device Vulkan0 -ngl 99 -c 8192 -np 1 \
  --jinja --reasoning-format deepseek \
  --temp 0.6 --top-p 0.95 --top-k 20 \
  --presence-penalty 0 --repeat-penalty 1
```

The sampling values follow Ornith's published precise-coding profile: temperature 0.6, top-p 0.95, top-k 20, presence penalty 0, and repetition penalty 1. [Ornith model instructions](https://github.com/ornith-ai/Ornith-1#quickstart)

For CPU-only inference, explicitly start another server with `-ngl 0`. It may be much slower; ZeroCoding does not switch to CPU silently.

In the TUI, run `/provider test` to check the local server and model endpoint.

## Configuration

Default configuration lives in `config/default.yaml`. User changes are saved to:

```txt
~/.zerocoding/config.yaml
```

Example provider config:

```yaml
provider: llama_cpp_local
mode: code
max_input_tokens: 4096
max_output_tokens: 1024
max_tool_rounds: 6
streaming_enabled: false

providers:
  llama_cpp_local:
    type: llama_cpp
    base_url: "http://127.0.0.1:8080/v1"
    model: "ornith-1.5-9b-q5-k-m"

modes:
  code:
    provider: llama_cpp_local
    model: "ornith-1.5-9b-q5-k-m"
    skills: []
```

The built-in `code`, `fast`, `reason` and `smart` modes use the same Ornith model; they adjust the output-token and tool-round budgets, not the model. ZeroCoding also sends the `reasoning_effort` request field, but the tested Ornith chat template reports that it does not support native effort control. Treat that field as ineffective for this model unless a later runtime/template check confirms otherwise. The model alias must match the `--alias` passed to `llama-server`. The GGUF path belongs to the server launch command and is not stored in ZeroCoding's shared config.

The llama.cpp server context (`-c`) must be at least the combined input and output budgets; the documented default is 5,120 tokens, so the launch example uses 8,192. When available, ZeroCoding counts the active chat template and tool schemas with llama.cpp `/apply-template` and `/tokenize`. Older conversation turns are dropped first when the input budget is exceeded. Legacy SQLite memory is preserved but is not appended to prompts, so unrelated sessions cannot inflate context.

Streaming is opt-in with `streaming_enabled: true`. The buffered response remains the default until the M7 task benchmark confirms comparable quality.

You can also use environment variables from `.env.example`.

## TUI Commands

- `/help` lists available commands.
- `/sessions` lists recent local sessions.
- `/sessions delete <full-id>` deletes one inactive session after explicit approval.
- `/sessions clear` deletes inactive saved sessions after explicit approval; the active session stays.
- `/session` shows the current session.
- `/resume <id>` resumes a previous session.
- `/new` starts a clean session.
- `/mode` lists configured modes.
- `/mode code`, `/mode reason`, `/mode fast` and `/mode smart` switch mode, provider and model for the current session.
- `/provider` lists configured providers.
- `/provider use llama_cpp_local` switches provider and saves it.
- `/provider add local llama_cpp http://127.0.0.1:8080/v1 ornith-1.5-9b-q5-k-m` adds a llama.cpp endpoint.
- `/provider remove local` removes a non-active provider.
- `/provider test` tests the active provider.
- `/config` opens a tabbed settings panel (Status, Config with search, Providers) like Claude Code's. `/provider` opens it on the Providers tab and `/model` opens the model picker (Enter sets the default, `s` uses it for this session only, ←/→ adjusts effort). Adding a provider is a short wizard: type from a list, name in a text box, address from presets or a custom box, and the model chosen from what the server actually serves (typed by hand only when it lists none). The typed commands keep working.
- The interactive UI is a fixed full-screen window (`fullscreen: true`, default): the transcript scrolls with PageUp/PageDown or the mouse wheel, the input box stays visible while the agent works (you can type, but sending waits until the task ends), Ctrl+C cancels the running task, and approvals show a Claude Code style diff (line numbers, red/green rows) that you accept with `Y`. Click the mascot at the top, or the small pet on the status row, to make it move. `fullscreen: false` returns to the classic scrollback UI.
- Small models sometimes print a command in a ```bash block instead of calling the tool. With `shell_block_fallback: true` (default) the runnable lines of such a block are offered as `run_command` calls and go through the usual approval. Blocks that need a shell (pipes, `&&`, redirects, `cd`) stay as text, and nothing is converted in Plan mode or after the model already changed something in that task.
- `/permission` chooses how actions are approved, for the current session only: `ask` (default), `auto` (commands from the `auto_packs` such as `mkdir`, `ls`, `cat`, `grep`, `git status` are approved by code when every path is inside the workspace; writes and edits still ask) and `yolo` (writes, edits and commands are approved after one confirmation, except commands with an argument that may leave the project — absolute paths, `~`, `..`, variables, symlinks out — which still ask; the command policy, workspace limits and Plan mode still apply). The mode shows on the left of the status row, and auto-approved actions stay in the transcript. `/permission packs` lists them. Ctrl+T expands or collapses diffs, including the ones already on screen; the Y/N decision is docked at the prompt so it never hides behind long output.
- `/buddy [work|look|dance|sleep|cheer|shock]` plays a mascot animation. With `mouse_support: true` (default) you can also click the small pet on the status row: the first click plays `work`, later ones pick an easter egg. The mouse costs plain text selection and wheel scrolling while the prompt is open (Shift+drag and Shift+wheel still work in most terminals); turn it off in `/config` → Mouse or with `mouse_support: false`.
- `/model` or `/model list` lists models when the provider supports it.
- `/model use ornith-1.5-9b-q5-k-m` switches model for the current session.
- `/plan [on|off]` enables read-only planning. Plan mode exposes only project listing, search and file reading to the agent.
- `/ultrathink [on|off]` adds output and tool-round budget for the current session.
- `/effort [low|medium|high]` selects the session budget profile.
- `/compact` folds older conversation into a short digest to free context. The prompt budget follows the server context window (`n_ctx`, read from llama.cpp `/props`; override with `context_window`), and large old tool outputs are compacted automatically at 70% of it.
- `/config` shows the active config.
- `/config base_url http://127.0.0.1:8080/v1` updates the active provider URL.
- `/config add local llama_cpp http://127.0.0.1:8080/v1 ornith-1.5-9b-q5-k-m` adds a provider.
- `/health` also tests the active provider.
- `/skills` lists Markdown skills.
- `/skill add spring` activates a skill without removing others.
- `/skill remove spring` deactivates a skill.
- `/skill active` lists active skills.
- `/skill clear` clears active skills.
- `/context` shows explicitly added context.
- `/context add src/main.py` adds a file to the next prompts.
- `/context remove src/main.py` removes a file from context.
- `/context tree` lists context files.
- `/context clear` clears context.
- `/read src/main.py` prints a file and adds it to context.
- `/tree` lists project files, ignoring generated and dependency folders.
- `/grep pattern` searches project files.
- `/metrics` summarizes local per-turn metrics (tokens, latency/TTFT when streaming is enabled, tool errors, trimmed history).
- `/mcp`, `/hooks` and `/plugins` show the configured extensions and their status.
- `/clear` clears the screen.
- `/exit` exits.

The interactive TUI clears the visible terminal on startup. Its prompt is framed by full-width rules, starts at one row and grows to six; it shows only Effort below the prompt, while `/status` lists the full session state. `Enter` submits; `Ctrl+J` inserts a newline. During a turn, the ghost animates beside a short status; the complete response is displayed when the turn finishes. Approval previews show the complete diff or command. Press `Y` to approve, `N` or `Esc` to deny; `Enter` or any other text denies. `Ctrl+C` cancels the running turn (nothing from it is saved to the session). One-shot `-m` requests do not receive tools and cannot execute changes.

## Extensions (all opt-in)

Configured in `~/.zerocoding/config.yaml` (commented examples in `config/default.yaml`). Details and cost limits: [docs/ROADMAP-m6.md](docs/ROADMAP-m6.md).

- **Hooks** run your own commands before/after tool calls or at turn end, under `command_policy`, with zero prompt cost. A failing `blocking: true` `pre_tool` hook refuses the call; no hook can approve anything. Failures of `post_tool` hooks are reported to the model; successes are silent.
- **MCP servers (stdio)** expose only allowlisted tools (`mcp__<server>__<tool>`), capped by `mcp.max_tools` (4) and `mcp.max_schema_tokens` (400), because every tool schema is sent with every request (~65 tokens each). Tools ask for approval unless marked `read_only: true`; read-only ones stay available in Plan mode. Their output is labeled as external data, truncated, and never treated as instructions. Servers get a minimal environment.
- **Subagent** (`subagents.enabled: true`): an `explore` tool that runs a read-only helper with its own context and returns a short summary. Sequential; saves context, not time.
- **Plugins**: folders in `~/.zerocoding/plugins/<name>/` with `skills/*.md`, `hooks.yaml` and `mcp.yaml`, activated by listing them under `plugins.enabled`. No plugin Python is executed; enabling a plugin trusts its hooks and MCP servers like your own config.
- **Metrics**: per-turn numbers (never prompts or answers) in `.zerocoding/metrics/turns.jsonl`; disable with `metrics_enabled: false`.

## Sessions

Interactive `zc` starts a local session with an ID. Sessions are stored as JSON files in:

```txt
~/.zerocoding/sessions
```

Each session stores provider, model, mode, Plan/Ultra/Effort state, active skills, project path, chat history and explicitly added context files. `/resume` restores that state; `/new` starts with Plan and Ultra off and Medium effort, using the configured provider, model and mode.

Sessions are plain local JSON and can contain prompts and tool results from the project. On POSIX systems, ZeroCoding restricts the session directory to the current user (`0700`) and session files to `0600`. This protects against other local accounts, not against the current user, malware or unencrypted backups. Set `session_persistence: false` in the config or start `zc --no-session-save` to keep the interactive session in memory only; it cannot be resumed after exit. Persistence is enabled by default for compatibility, and sessions are never removed automatically.

```txt
/sessions
/resume a1b2c3d4e5f60718293a4b5c6d7e8f90
/sessions delete a1b2c3d4e5f60718293a4b5c6d7e8f90
/sessions clear
/new
```

New sessions use 32-character UUIDs. Existing 8-character session IDs remain valid; `/resume` accepts a prefix only when it matches one saved session. An unknown or malformed resume request leaves the current session intact. `/sessions` reports unreadable session files by ID without displaying their contents, so they can be removed explicitly with `/sessions delete <full-id>`.

## Project Context

ZeroCoding never reads project files automatically for prompts. Add context explicitly:

```txt
/context add src/zerocoding/cli.py
/context tree
```

`/read <path>` prints the file and also adds it to the temporary context. Context has per-file and total size limits, and ignores `.git`, `node_modules`, `venv`, `.venv`, `__pycache__`, `target`, `dist` and `build`.

## Skills

Skills are Markdown files in [skills/](/home/kona/Projetos/ZeroCoding/skills). Frontmatter is supported:

```md
---
name: spring
description: Padrões para projetos Java Spring Boot
---

Use Java 21.
Use Spring Boot 3.
Use DTOs.
```

Activate a skill in the TUI:

```txt
/skill add spring
/skill add python
/skill active
```

## Architecture

- `core/config.py` loads defaults, user config and environment overrides.
- `core/sessions.py` stores local JSON sessions.
- `core/project_context.py` manages explicit project context, tree and grep.
- `providers/base.py` defines `generate`, `chat`, health checks and model listing. The OpenAI-compatible provider also exposes the optional streaming turn used when `streaming_enabled` is set.
- `providers/llama_cpp.py` adapts llama.cpp's OpenAI-compatible server, including native effort requests.
- `providers/ollama.py` is a **legacy** adapter for native Ollama endpoints (`/api/generate`, `/api/chat`, `/api/tags`). It is kept for existing configurations, is not validated against a real Ollama server, and receives no new features; llama.cpp is the supported runtime.
- `providers/openai_compatible.py` supports `/chat/completions` and `/models`.
- `core/agent.py` budgets prompts, runs bounded structured tool-call loops and tracks active skills.
- `core/tools.py` provides workspace-scoped file reading/search and approval-gated `write_file`, `edit_file` and `run_command` (filtered by `core/command_policy.py`), and hosts extension tools.
- `core/hooks.py`, `mcp/` (client + manager), `core/subagent.py`, `core/plugins.py` and `core/bootstrap.py` implement the opt-in extensions; `core/metrics.py` and `core/cancel.py` provide per-turn metrics and turn cancellation.
- `tui/app.py` provides the purple Rich-based terminal interface.
- `tui/textual_app.py` is a prepared Textual prototype for future expansion.

## Development

```bash
uv run python -m unittest discover -s tests -p 'test_*.py'
uv run python -m py_compile src/zerocoding/**/*.py
```

## Roadmap

See [docs/ROADMAP.md](docs/ROADMAP.md) for the milestone plan, baseline, deliverables and acceptance criteria.
