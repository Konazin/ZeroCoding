# M1 UI stack comparison

The prototypes exercise the same canned flow without loading provider configuration, contacting a model, inspecting project files, or executing tools.

## Launch

From the repository root, sync the production dependencies and run the Rich prototype:

```sh
uv sync --locked
uv run python -m zerocoding.tui.demo rich
```

Textual is an optional comparison prototype. Install it only when you want to run that variant:

```sh
uv sync --locked --extra prototype
uv run python -m zerocoding.tui.demo textual
```

To collect startup, memory, and idle CPU figures with five fresh launches per stack, run the Linux PTY sampler:

```sh
uv run python scripts/measure_m1_ui.py
```

It uses the same 80×24 terminal size for both prototypes, then samples RSS after 30 seconds and CPU over the next 60 seconds. The full comparison takes a few minutes. It reads `/proc` and exits each child through the prototype's `/quit` command.

Both prototypes show the welcome layout, multiline composer, slash completion, transcript, working indicator, compact tool rows, approval card, and error state. The Rich version uses a classic scrollback flow. The Textual version keeps its header, transcript, status, and composer in a full-screen layout.
The model/provider label is fixed to the current default (`Ollama · deepseek-coder-v2`) for comparison; it does not connect to Ollama. Each prototype stores up to 200 submitted prompts per workspace under the user's data directory (`$XDG_DATA_HOME/zerocoding/history/` on Linux).

## Scenario review

Run the same sequence in each prototype:

1. Type a normal prompt to see the user message, animated work state, response, and elapsed duration.
2. Run `/demo tool` to see read/search rows and factual stage labels.
3. Run `/demo approval`; change the selected action with Up/Down, then confirm with Enter, or use `Y`, `N`, or `Esc` directly.
4. Run `/demo error` to see the error state.
5. Type `/` to inspect completion, use arrows to move through suggestions, and Tab to complete. Enter submits; Ctrl+J inserts a newline.

The footer hint is selected once per process. Work phrases are selected once per stage. The mascot animation and sparkle spinner are separate; no model reasoning or token stream is simulated.

## Local overhead record

Run the sampler on the target PC with no model process running. It measures fresh-process startup five times and the idle UI for 90 seconds per stack. Record the terminal, OS, and Python version alongside the values.

| Prototype | Cold startup median (s) | RSS at 30 s (MiB) | Idle CPU average (%) |
| --- | ---: | ---: | ---: |
| Rich + prompt_toolkit | 0.204 | 41.1 | 0.02 |
| Textual | 0.332 | 49.8 | 0.45 |

Measured on the target host with Python 3.13.15, Linux 6.18.55, `xterm-kitty`, and an 80×24 PTY. The host CPU is an AMD Ryzen 5 4600G; system memory is 16 GB.

The user selected Rich + prompt_toolkit for production, prioritizing lower idle CPU and memory while keeping a classic scrollback flow. Textual remains an optional comparison prototype and is not installed by the default `uv sync`. M1 was completed after the user's final review on 2026-10-12; M2 is now in progress.

