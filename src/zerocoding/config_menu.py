"""Interactive /config: one place for provider, model, effort and streaming.

Follows Claude Code's conventions: a short list of personal options, Enter saves, `s` in the model
picker applies to this session only, and every flow can be cancelled with Esc. Each action reuses
the existing slash commands, so the typed commands and the menu cannot drift apart.
"""
from __future__ import annotations

DEFAULT_URLS = {"openai_compatible": "http://127.0.0.1:11434/v1", "llama_cpp": "http://127.0.0.1:8080/v1"}
TYPE_CHOICES = (
    ("openai_compatible", "Ollama, LM Studio, vLLM and other OpenAI-style servers"),
    ("llama_cpp", "llama.cpp llama-server (exact token counts)"),
)


def run_config_menu(tui, config, manager, agent, dispatch) -> None:
    """`dispatch(command)` runs a slash command and applies the provider it returns to the agent."""
    while True:
        active = config.active_provider
        rows = [
            ("Provider", f"{config.provider} · {active.type}"),
            ("Model", agent_model(config, agent)),
            ("Effort", agent.effort.title()),
            ("Streaming", "on" if config.streaming_enabled else "off"),
            ("Mouse", "on · click the pet" if config.mouse_support else "off · plain terminal selection and scrolling"),
            ("Add provider…", "connect another server"),
            ("Remove provider…", ""),
        ]
        picked = tui.select("Settings", rows)
        if picked is None:
            return
        choice = rows[picked[0]][0]
        if choice == "Provider":
            _pick_provider(tui, config, dispatch)
        elif choice == "Model":
            _pick_model(tui, config, manager, agent, dispatch)
        elif choice == "Effort":
            _pick_effort(tui, agent, dispatch)
        elif choice == "Streaming":
            config.streaming_enabled = not config.streaming_enabled
            agent.streaming_enabled = config.streaming_enabled
            manager.save(config)
            tui.show_success(f"Streaming {'on' if config.streaming_enabled else 'off'}.")
        elif choice == "Mouse":
            config.mouse_support = not config.mouse_support
            tui.mouse_enabled = config.mouse_support
            manager.save(config)
            tui.show_success(f"Mouse {'on' if config.mouse_support else 'off'}.")
        elif choice == "Add provider…":
            _add_provider(tui, config, dispatch)
        else:
            _remove_provider(tui, config, dispatch)


def agent_model(config, agent) -> str:
    return getattr(agent.provider, "model", "") or config.model


def _pick_provider(tui, config, dispatch):
    names = list(config.providers)
    rows = [(name, f"{config.providers[name].base_url} · {config.providers[name].model}"
             + ("  (active)" if name == config.provider else "")) for name in names]
    picked = tui.select("Switch provider", rows, current=names.index(config.provider))
    if picked is not None and names[picked[0]] != config.provider:
        dispatch(f"/provider use {names[picked[0]]}")


def _served_models(agent):
    try:
        return list(agent.provider.list_models())
    except Exception:
        return []


def _pick_model(tui, config, manager, agent, dispatch):
    models = _served_models(agent)
    current = agent_model(config, agent)
    if not models:
        typed = tui.ask("Model name (the server did not list any):", current)
        if typed:
            dispatch(f"/model use {typed}")
        return
    picked = tui.select(
        "Select model", [(m, "(current)" if m == current else "") for m in models],
        current=models.index(current) if current in models else 0,
        extra_keys={"s": "this session only"},
    )
    if picked is None:
        return
    model, key = models[picked[0]], picked[1]
    dispatch(f"/model use {model}")
    if key != "s":  # Enter also saves it as the provider's default
        config.active_provider.model = model
        manager.save(config)
        tui.show_success(f"Saved {model} as the default for {config.provider}.")


def _pick_effort(tui, agent, dispatch):
    levels = ["low", "medium", "high"]
    hints = {"low": "fast, short answers", "medium": "default", "high": "slower, more tool rounds"}
    picked = tui.select("Effort", [(level.title(), hints[level]) for level in levels],
                        current=levels.index(agent.effort) if agent.effort in levels else 1)
    if picked is not None:
        dispatch(f"/effort {levels[picked[0]]}")


def _add_provider(tui, config, dispatch):
    kind = tui.select("Provider type", list(TYPE_CHOICES))
    if kind is None:
        return
    provider_type = TYPE_CHOICES[kind[0]][0]
    name = tui.ask("Name:", "ollama" if provider_type == "openai_compatible" else "local")
    if not name or name in config.providers:
        if name:
            tui.show_error(f"A provider named '{name}' already exists.")
        return
    url = tui.ask("Base URL:", DEFAULT_URLS[provider_type])
    if not url:
        return
    # Probe with a throwaway provider so the model can be chosen from what the server actually serves.
    from .providers.llama_cpp import LlamaCppProvider
    from .providers.openai_compatible import OpenAICompatibleProvider
    probe = (LlamaCppProvider if provider_type == "llama_cpp" else OpenAICompatibleProvider)("", url, "")
    try:
        models = list(probe.list_models())
    except Exception as exc:
        tui.show_error(f"Could not reach {url}: {exc}")
        models = []
    if models:
        picked = tui.select("Model", models)
        model = models[picked[0]] if picked else ""
    else:
        model = tui.ask("Model name:", "") or ""
    if model:
        dispatch(f"/provider add {name} {provider_type} {url} {model}")


def _remove_provider(tui, config, dispatch):
    names = [name for name in config.providers if name != config.provider]
    if not names:
        tui.show_info("Only the active provider is configured; switch to another one before removing it.")
        return
    picked = tui.select("Remove provider", names)
    if picked is not None:
        dispatch(f"/provider remove {names[picked[0]]}")
