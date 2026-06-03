# ZeroCoding

ZeroCoding is an open source terminal coding assistant built in Python. It is inspired by the general experience of modern coding agents in the terminal, but uses its own identity, interface text, provider layer and ghost ASCII logo.

The MVP focuses on a clean purple transcript-style TUI where you can choose a provider, configure local Ollama, select a model, keep sessions, add explicit project context, receive streamed responses and activate multiple Markdown skills.

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
ollama pull deepseek-coder-v2
```

ZeroCoding ships with `ollama_local` configured for:

```txt
http://localhost:11434
```

Inside the TUI you can test it with:

```txt
/provider test
```

Use a main PC as an Ollama server for a notebook on the same LAN:

```bash
# On the main PC
OLLAMA_HOST=0.0.0.0:11434 ollama serve

# On the notebook, inside ZeroCoding
/provider add ollama_lan ollama http://192.168.0.50:11434 deepseek-coder-v2
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
    model: "deepseek-coder-v2"

  qwen_api:
    type: openai_compatible
    base_url: "https://example.com/v1"
    api_key_env: "QWEN_API_KEY"
    model: "qwen-max"

mode: code

modes:
  code:
    provider: ollama_local
    model: "deepseek-coder-v2"
    skills: []

  reason:
    provider: ollama_local
    model: "deepseek-r1:8b"
    skills: []
```

You can also use environment variables from [.env.example](/home/kona/programas/zerocoding/.env.example).

## TUI Commands

- `/help` lists available commands.
- `/sessions` lists recent local sessions.
- `/session` shows the current session.
- `/resume <id>` resumes a previous session.
- `/new` starts a clean session.
- `/mode` lists configured modes.
- `/mode code`, `/mode reason`, `/mode fast` and `/mode smart` switch mode, provider and model.
- `/provider` lists configured providers.
- `/provider use ollama_local` switches provider and saves it.
- `/provider add local ollama http://localhost:11434 qwen2.5-coder:7b` adds a provider.
- `/provider remove local` removes a non-active provider.
- `/provider test` tests the active provider.
- `/model` or `/model list` lists models when the provider supports it.
- `/model use deepseek-coder-v2` switches model and saves it.
- `/config` shows the active config.
- `/config base_url http://localhost:11434` updates the active provider URL.
- `/config add local ollama http://localhost:11434 qwen2.5-coder:7b` adds a provider.
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
- `/clear` clears the screen.
- `/exit` exits.

## Sessions

Interactive `zc` starts a local session with an ID. Sessions are stored as JSON files in:

```txt
~/.zerocoding/sessions
```

Each session stores provider, model, mode, active skills, project path, chat history and explicitly added context files.

```txt
/sessions
/resume a1b2c3d4
/new
```

## Project Context

ZeroCoding never reads project files automatically for prompts. Add context explicitly:

```txt
/context add src/zerocoding/cli.py
/context tree
```

`/read <path>` prints the file and also adds it to the temporary context. Context has per-file and total size limits, and ignores `.git`, `node_modules`, `venv`, `.venv`, `__pycache__`, `target`, `dist` and `build`.

## Skills

Skills are Markdown files in [skills/](/home/kona/programas/zerocoding/skills). Frontmatter is supported:

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
- `providers/base.py` defines `generate`, `chat`, `chat_stream`, `healthcheck` and `list_models`.
- `providers/ollama.py` supports native Ollama endpoints `/api/generate`, `/api/chat` and `/api/tags`.
- `providers/openai_compatible.py` supports `/chat/completions` and `/models`.
- `core/agent.py` builds prompts, calls providers and tracks multiple active skills.
- `tui/app.py` provides the purple Rich-based terminal interface.
- `tui/textual_app.py` is a prepared Textual prototype for future expansion.

## Development

```bash
PYTHONPATH=src python -m unittest discover -s tests -p 'test_*.py'
PYTHONPATH=src python -m py_compile src/zerocoding/**/*.py
```

## Roadmap

- Add a richer provider configuration modal.
- Add optional streaming for OpenAI-compatible APIs.
- Add file editing tools after the chat MVP is stable.
- Add shell/git tools behind clear safety prompts.

## Current TODO

File editing, shell execution and autonomous agent loops are intentionally not implemented in the MVP.
