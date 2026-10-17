"""Settings flows built on the screens in tui/menus.py: /config, /provider and /model without arguments.

Conventions copied from Claude Code: a tabbed panel with a searchable list, Enter sets a default,
`s` in the model picker applies to this session only, Esc backs out. Values that have a small set of
valid answers are chosen from lists; free text (names, custom URLs) goes through validated text boxes;
the model is offered from what the server actually serves, and typed by hand only when it cannot say.
Every action reuses the typed slash commands, so menu and commands cannot drift apart.
"""
from __future__ import annotations

import re

from . import __version__
from .core.router import build_session_provider
from .tui.menus import InputScreen, Row, SelectScreen, SettingsScreen, Tab

TYPE_ROWS = (
    ("openai_compatible", "Ollama, LM Studio, vLLM and other OpenAI-style servers"),
    ("llama_cpp", "llama.cpp llama-server, exact token counts"),
)
URL_PRESETS = {
    "openai_compatible": (("Ollama", "http://127.0.0.1:11434/v1"), ("LM Studio", "http://127.0.0.1:1234/v1"),
                          ("vLLM / other", "http://127.0.0.1:8000/v1")),
    "llama_cpp": (("llama-server", "http://127.0.0.1:8080/v1"),),
}
NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
EFFORTS = ["low", "medium", "high"]


def run_settings(tui, config, manager, agent, dispatch, tab: str = "Config") -> None:
    """Open the tabbed panel; each Enter runs one action and reopens the panel on the same tab."""
    connection = {}

    def status_lines():
        if "value" not in connection:
            try:
                connection["value"] = "online" if agent.provider.healthcheck() else "offline"
            except Exception:
                connection["value"] = "offline"
        active = config.active_provider
        return [
            ("Version", __version__), ("Provider", f"{config.provider} ({active.type})"),
            ("Model", _current_model(config, agent)), ("Base URL", active.base_url),
            ("Connection", connection["value"]), ("Effort", agent.effort.title()),
            ("Streaming", str(config.streaming_enabled).lower()), ("Config file", str(manager.user_config_path)),
        ]

    def config_rows():
        return [
            Row("Provider", config.provider, "provider"),
            Row("Model", _current_model(config, agent), "model"),
            Row("Effort", agent.effort, "effort"),
            Row("Permission mode", getattr(getattr(agent, "permissions", None), "mode", "ask"), "permission"),
            Row("Streaming", str(config.streaming_enabled).lower(), "streaming"),
            Row("Mouse (click the pet)", str(config.mouse_support).lower(), "mouse"),
            Row("Save sessions", str(config.session_persistence).lower(), "persist"),
        ]

    def provider_rows():
        rows = [Row(name, f"{p.base_url} · {p.model}", name, checked=name == config.provider)
                for name, p in config.providers.items()]
        return rows + [Row("+ Add provider…", "", "__add__")]

    while True:
        screen = SettingsScreen([
            Tab("Status", lines=status_lines),
            Tab("Config", rows=config_rows, searchable=True),
            Tab("Providers", rows=provider_rows),
        ], tab=tab)
        done = tui.run_screen(screen)
        if done.cancelled:
            return
        tab, row = done.value
        if tab == "Providers":
            _add_provider(tui, config, dispatch) if row == "__add__" else _provider_actions(tui, config, row, dispatch)
        elif row == "provider":
            tab = "Providers"
        elif row == "model":
            pick_model(tui, config, manager, agent, dispatch)
        elif row == "effort":
            _pick_effort(tui, agent, dispatch)
        elif row == "permission" and getattr(agent, "permissions", None) is not None:
            pick_permission(tui, agent.permissions)
        elif row in {"streaming", "mouse", "persist"}:
            _toggle(tui, config, manager, agent, row)


def _current_model(config, agent) -> str:
    return getattr(agent.provider, "model", "") or config.model


def _toggle(tui, config, manager, agent, row) -> None:
    if row == "streaming":
        config.streaming_enabled = agent.streaming_enabled = not config.streaming_enabled
    elif row == "mouse":
        config.mouse_support = tui.mouse_enabled = not config.mouse_support
    else:
        config.session_persistence = not config.session_persistence
    manager.save(config)


def _pick_effort(tui, agent, dispatch) -> None:
    hints = {"low": "fast, short answers", "medium": "default", "high": "slower, more tool rounds"}
    rows = [Row(level.title(), hints[level], level, checked=level == agent.effort) for level in EFFORTS]
    done = tui.run_screen(SelectScreen("Effort", rows, index=EFFORTS.index(agent.effort) if agent.effort in EFFORTS else 1))
    if not done.cancelled:
        dispatch(f"/effort {EFFORTS[done.value]}")


def served_models(provider) -> list[str]:
    try:
        return list(provider.list_models())
    except Exception:
        return []


def pick_model(tui, config, manager, agent, dispatch) -> None:
    """/model picker: models come from the server; Enter saves the default, `s` is session-only."""
    current = _current_model(config, agent)
    models = served_models(agent.provider)
    if not models:
        tui.show_warning(f"{config.provider} did not list its models. Type the exact name.")
        done = tui.run_screen(InputScreen("Model name", f"Exact model name on {config.active_provider.base_url}",
                                          default=current, validate=lambda v: None if v else "Enter a model name.", icon="›"))
        if not done.cancelled:
            dispatch(f"/model use {done.value}")
            config.active_provider.model = done.value
            manager.save(config)
        return
    rows = [Row(m, "current" if m == current else "", m, checked=m == current) for m in models]
    screen = SelectScreen(
        "Select model", rows, index=models.index(current) if current in models else 0,
        subtitle=f"Models served by {config.provider}. Your pick becomes the default for this provider.",
        extra_keys={"s": "to use this session only"}, enter_text="Enter to set as default",
        adjust=("effort", EFFORTS, agent.effort),
    )
    done = tui.run_screen(screen)
    if done.cancelled:
        return
    model = models[done.value]
    dispatch(f"/model use {model}")
    if done.key != "s":
        config.active_provider.model = model
        manager.save(config)
        tui.show_success(f"{model} is now the default for {config.provider}.")
    if screen.adjusted != agent.effort:
        dispatch(f"/effort {screen.adjusted}")


def _provider_actions(tui, config, name, dispatch) -> None:
    rows = [Row("Use this provider", "", "use"), Row("Test connection", "", "test"), Row("Remove", "", "remove")]
    done = tui.run_screen(SelectScreen(name, rows, subtitle=f"{config.providers[name].base_url} · {config.providers[name].model}"))
    if done.cancelled:
        return
    action = rows[done.value].id
    if action == "use":
        dispatch(f"/provider use {name}")
    elif action == "remove":
        dispatch(f"/provider remove {name}")
    else:
        _test_provider(tui, config, name)


def _test_provider(tui, config, name) -> None:
    entry = config.providers[name]
    try:
        provider = build_session_provider(config, name, entry.model)
        if not provider.healthcheck():
            tui.show_error(f"{name} is offline at {entry.base_url}.")
            return
        models = served_models(provider)
    except Exception as exc:
        tui.show_error(f"{name}: {exc}")
        return
    if models and entry.model not in models:
        tui.show_warning(f"{name} is online but does not serve '{entry.model}'. Available: {', '.join(models[:8])}.")
    else:
        tui.show_success(f"{name} is online and serves {entry.model}." if models else f"{name} is online.")


def _add_provider(tui, config, dispatch) -> None:
    """Wizard: type (list) -> name (box) -> URL (presets or box) -> model (fetched list, else box)."""
    kind = tui.run_screen(SelectScreen("Add provider", [Row(t, note, t) for t, note in TYPE_ROWS],
                                       subtitle="What kind of server is it?"))
    if kind.cancelled:
        return
    provider_type = TYPE_ROWS[kind.value][0]

    def check_name(value):
        if not NAME_PATTERN.match(value):
            return "Use letters, digits, '-', '_' or '.', starting with a letter or digit."
        return "That name is already used." if value in config.providers else None

    suggestion = "ollama" if provider_type == "openai_compatible" else "llama"
    name = tui.run_screen(InputScreen("Provider name", "A short label to switch to it later.",
                                      fallback="" if suggestion in config.providers else suggestion, validate=check_name, icon="›"))
    if name.cancelled:
        return
    url = _choose_url(tui, provider_type)
    if not url:
        return
    models = _probe_models(tui, provider_type, url)
    if models:
        picked = tui.run_screen(SelectScreen("Select model", [Row(m, "", m) for m in models],
                                             subtitle=f"{len(models)} served by {url}"))
        model = models[picked.value] if not picked.cancelled else ""
    else:
        typed = tui.run_screen(InputScreen("Model name", "The server did not list models; type the exact name.",
                                           validate=lambda v: None if v else "Enter a model name.", icon="›"))
        model = typed.value if not typed.cancelled else ""
    if model:
        dispatch(f"/provider add {name.value} {provider_type} {url} {model}")


def _choose_url(tui, provider_type) -> str:
    presets = URL_PRESETS[provider_type]
    rows = [Row(label, url, url) for label, url in presets] + [Row("Custom URL…", "", None)]
    done = tui.run_screen(SelectScreen("Server address", rows, subtitle="Where is it running?"))
    if done.cancelled:
        return ""
    if rows[done.value].id:
        return rows[done.value].id

    def check_url(value):
        return None if re.match(r"^https?://\S+$", value) else "Start with http:// or https://, no spaces."

    typed = tui.run_screen(InputScreen("Server address", "Include the /v1 path, e.g. http://host:11434/v1",
                                       default="http://", validate=check_url, icon="›"))
    return "" if typed.cancelled else typed.value.rstrip("/")


def _probe_models(tui, provider_type, url) -> list[str]:
    """One quick request to see which models the server offers; failure leaves the choice to the user."""
    from .providers.llama_cpp import LlamaCppProvider
    from .providers.openai_compatible import OpenAICompatibleProvider
    probe = (LlamaCppProvider if provider_type == "llama_cpp" else OpenAICompatibleProvider)("", url, "")
    try:
        models = list(probe.list_models())
    except Exception as exc:
        tui.show_warning(f"Could not read the model list from {url} ({exc}). You can still type it.")
        return []
    if not models:
        tui.show_warning(f"{url} answered but listed no models.")
    return models


def confirm_yolo(tui) -> bool:
    return tui.confirm_action(
        "Enable YOLO mode",
        "Every write, edit and command is approved without asking until you switch back.\n"
        "The command policy, workspace limits and Plan mode still apply.",
    )


def pick_permission(tui, policy) -> None:
    """Session-only approval mode; YOLO needs an explicit confirmation."""
    from .core.permissions import MODE_SUMMARY, MODES
    rows = [Row(mode, MODE_SUMMARY[mode], mode, checked=mode == policy.mode) for mode in MODES]
    done = tui.run_screen(SelectScreen(
        "Permission mode", rows, index=MODES.index(policy.mode),
        subtitle="Applies to this session only and resets to ask when you reopen ZeroCoding.",
    ))
    if done.cancelled:
        return
    mode = MODES[done.value]
    if mode == "yolo" and policy.mode != "yolo" and not confirm_yolo(tui):
        return
    policy.set_mode(mode)
    tui.show_success(f"Permission mode: {mode}.")
