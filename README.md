# ZeroCoding

ZeroCoding is an open source terminal coding assistant built in Python. It is inspired by the general experience of modern coding agents in the terminal, but uses its own identity, interface text, provider layer and ghost ASCII logo.

The TUI uses a persistent full-screen layout, a compact animated ghost, a scrollable transcript and a fixed input area. It keeps the Python installation lightweight and limits prompt context for local models.

## Install

```bash
pip install -e .
```

Run it with either command:

```bash
zerocoding
zc
```

Send a one-shot prompt:

```bash
zc -m "Explique este projeto em poucas linhas"
```

## Ollama

Start Ollama locally:

```bash
ollama serve
```

Pull a coding model:

```bash
ollama pull qwen2.5-coder:7b
```

ZeroCoding ships with `ollama_local` configured for:

```txt
http://localhost:11434
```

Inside the TUI you can test it with:

```txt
/provider test
```

At startup and before `zc init`, ZeroCoding checks the active provider; for Ollama it also checks that the configured model is installed. If another local model is available, choose it from the list. ZeroCoding does not download models automatically.

Use a main PC as an Ollama server for a notebook on the same LAN:

```bash
# On the main PC
OLLAMA_HOST=0.0.0.0:11434 ollama serve

# On the notebook, inside ZeroCoding
/provider add ollama_lan ollama http://192.168.0.50:11434 qwen2.5-coder:7b
/provider use ollama_lan
/provider test
```

## Configuration

Default configuration lives in [config/default.yaml](/home/kona/programas/zerocoding/config/default.yaml). User changes are saved to:

```txt
~/.zerocoding/config.yaml
```

Example provider config:

```yaml
provider: ollama_local

providers:
  ollama_local:
    type: ollama
    base_url: "http://localhost:11434"
    model: "qwen2.5-coder:7b"

  qwen_api:
    type: openai_compatible
    base_url: "https://example.com/v1"
    api_key_env: "QWEN_API_KEY"
    model: "qwen-max"

mode: code

modes:
  code:
    provider: ollama_local
    model: "qwen2.5-coder:7b"
    skills: []

  project:
    provider: ollama_local
    model: "qwen2.5-coder:7b"
    input_budget_tokens: 2048
    output_budget_tokens: 1024
    max_tool_steps: 8
    skills: []

  reason:
    provider: ollama_local
    model: "deepseek-r1:8b"
    skills: []

mcp_servers:
  filesystem:
    transport: stdio
    command: "uvx"
    args: ["mcp-server-filesystem", "."]
```

You can also use environment variables from [.env.example](/home/kona/programas/zerocoding/.env.example).

## TUI Commands

- `/help` lists available commands.
- `/sessions` lists recent local sessions.
- `/session` shows the current session.
- `/resume <id>` resumes a previous session.
- `/new` starts a clean session.
- `/mode` lists configured modes.
- `/mode code`, `/mode reason`, `/mode fast`, `/mode smart` and `/mode project` switch mode, provider and model.
- `/permissions` shows the active permission mode; use `/permissions manual`, `/permissions approve-for-me` or `/permissions full-access` to change it.
- `/provider` lists configured providers.
- `/provider use ollama_local` switches provider and saves it.
- `/provider add` opens a guided setup for provider name, type, URL, model and API key environment variable.
- `/provider add local ollama http://localhost:11434 qwen2.5-coder:7b` adds a provider.
- `/provider remove local` removes a non-active provider.
- `/provider test` tests the active provider.
- `/model` or `/model list` lists models when the provider supports it.
- `/model use qwen2.5-coder:7b` switches model and saves it.
- `/config` shows the active config.
- `/config base_url http://localhost:11434` updates the active provider URL.
- `/config add local ollama http://localhost:11434 qwen2.5-coder:7b` adds a provider.
- `/health` also tests the active provider.
- `/skills` lists Markdown skills.
- `/mcp` lists configured MCP servers and supports explicit tools, resources and prompt commands.
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
- `/clear` clears the screen.
- `Ctrl-C` cancels the current generation; `Ctrl-D` exits.
- `/exit` exits.

## Prompt budgets and performance

The permanent system prompt stays below 64 estimated tokens. Project context, active Skills and recent history share a per-mode input budget. `fast`, `code`, `reason` and `smart` reserve 512 output tokens; `project` uses 2,048 input tokens, up to 1,024 output tokens and 8 tool steps. Other defaults are `fast` 1,024 input / 3 tool steps, `code` 2,048 / 6, and `reason` and `smart` 3,072 / 8. Estimates use four characters per token unless the provider reports usage.

`/status` shows the active profile and available timings: prompt assembly, estimated input tokens, first token, total response time, tools and provider-reported usage. Metrics stay in memory and never store prompts or file contents. See [PERFORMANCE.md](/home/kona/programas/zerocoding/PERFORMANCE.md) for comparison guidance and the threshold for considering optional Rust acceleration.

## Permission modes

The default is `manual`. `approve-for-me` sends each local write to the active provider in a separate review call; invalid or unavailable reviews deny the action. Local commands still require your confirmation when a working sandbox is unavailable. `full-access` skips prompts for local project actions and runs commands inside Linux bubblewrap with network disabled. It is unavailable unless the sandbox self-check succeeds. Network use, MCP and dependency installation always require your confirmation.

## Create a project

From the parent directory, run:

```bash
zc init ./my-project
```

Choose Python, JavaScript or TypeScript, then `cli` or `api`, and describe the project. Python CLI scaffolds use `argparse` and `unittest`; Python APIs use FastAPI and `pytest`/`httpx`. JavaScript and TypeScript CLIs use Node.js 24+, `node:test` and Node built-ins; APIs use Fastify 5 and `app.inject` tests. The target must be a new or empty child directory of the current directory. ZeroCoding shows the file list and applies the active permission mode to scaffold creation and code edits. Generation cannot run commands. Verification and dependency installation have separate approvals; absent dependencies are reported as unverified, and no server starts automatically.

## Sessions

Interactive `zc` starts a local session with an ID. Sessions are stored as JSON files in:

```txt
~/.zerocoding/sessions
```

Each session stores provider, model, mode, active skills, project path, chat history and explicitly added context files. JSON session history is the only conversation source; old global SQLite transcripts are not loaded into prompts.

```txt
/sessions
/resume a1b2c3d4
/new
```

## Project Context

ZeroCoding keeps explicit context small. The agent can read and search project files through tools when useful; direct context can also be added explicitly:

```txt
/context add src/zerocoding/cli.py
/context tree
```

`/read <path>` prints a file and adds it to session context. File tools stay inside the project root. Manual mode confirms writes and commands; automatic modes cover only local project actions, and commands run in the workspace sandbox. Commands use argv arrays without shell expansion. Network, MCP and dependency-install actions still require confirmation.

## Skills

Skills can be Markdown files in [skills/](/home/kona/programas/zerocoding/skills) or directories containing `SKILL.md`. Metadata is discovered without loading full instructions; `/skill add` loads content into the prompt. Project Skills override user Skills, which override bundled Skills. Frontmatter is supported:

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

Search paths are the configured `skills_path`, `~/.zerocoding/skills`, and `.zerocoding/skills` in the project.

## MCP

MCP is optional and starts with local `stdio` servers. Install it with `pip install 'zerocoding[mcp]'`, then configure servers in `~/.zerocoding/config.yaml`:

```yaml
mcp_servers:
  filesystem:
    transport: stdio
    command: "uvx"
    args: ["mcp-server-filesystem", "."]
```

MCP tools ask for confirmation on each call. `/mcp` lists servers; `/mcp tools`, `/mcp resources NAME`, `/mcp read NAME URI`, `/mcp prompts NAME`, and `/mcp prompt NAME PROMPT` expose other MCP features explicitly.

Set server environment values from the environment with entries such as `API_TOKEN: "${API_TOKEN}"` under that server's `env` map.

## Architecture

- `core/config.py` loads defaults, user config and environment overrides.
- `core/sessions.py` stores local JSON sessions.
- `core/project_context.py` manages explicit project context, tree and grep.
- `providers/base.py` defines `generate`, `chat`, `chat_stream`, `healthcheck` and `list_models`.
- `providers/ollama.py` supports native Ollama endpoints `/api/generate`, `/api/chat` and `/api/tags`.
- `providers/openai_compatible.py` supports `/chat/completions` and `/models`.
- `core/agent.py` builds bounded prompts, runs provider tool calls and tracks active skills.
- `tools/registry.py` defines the shared interface for built-in and MCP tools.
- `core/events.py` defines the typed runtime events consumed by the host.
- `tui/app.py` provides the full-screen prompt_toolkit host and Rich command output.
- The TUI keeps the original ZeroCoding ghost in its header and updates its expression by agent state.

## Development

```bash
PYTHONPATH=src python -m unittest discover -s tests -p 'test_*.py'
PYTHONPATH=src python -m py_compile src/zerocoding/**/*.py
```

## Future work

- Add Streamable HTTP or SSE MCP transports when a concrete use case requires them.
- Add MCP Streamable HTTP if a concrete remote-server use case appears.

## Current TODO

The agent can read and search automatically; file writes, command execution, and MCP calls require confirmation.
