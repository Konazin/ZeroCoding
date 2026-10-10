"""Full-screen ZeroCoding terminal interface with Rich command output."""
from __future__ import annotations

import io
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from rich.console import Console
    from rich.columns import Columns
    from rich.markdown import Markdown
    from rich.padding import Padding
    from rich.panel import Panel
    from rich.syntax import Syntax
    from rich.text import Text

    HAS_RICH = True
except ImportError:
    HAS_RICH = False

from zerocoding import __version__
from zerocoding.tools.registry import format_tool_preview

from .theme import (
    BG as ZERO_BG,
    COMMANDS,
    DARK as ZERO_DARK,
    GHOST_FULL,
    GHOST_FRAMES,
    GHOST_STATE_LABELS,
    GRAY as ZERO_GRAY,
    GREEN as ZERO_GREEN,
    LIGHT as ZERO_LIGHT,
    PURPLE as ZERO_PURPLE,
    PURPLE_LIGHT as ZERO_PURPLE_LIGHT,
    RED as ZERO_RED,
    USER_BG as ZERO_USER_BG,
    YELLOW as ZERO_YELLOW,
)
from .mascot import render_mascot

try:
    import asyncio
    import queue
    import threading
    from prompt_toolkit import PromptSession
    from prompt_toolkit.application import Application
    from prompt_toolkit.completion import Completer, Completion
    from prompt_toolkit.buffer import Buffer
    from prompt_toolkit.formatted_text import HTML
    from prompt_toolkit.history import InMemoryHistory
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.layout import ConditionalContainer, Float, FloatContainer, HSplit, Layout, VSplit, Window
    from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
    from prompt_toolkit.layout.dimension import Dimension
    from prompt_toolkit.layout.menus import CompletionsMenu
    from prompt_toolkit.filters import Condition
    from prompt_toolkit.application.run_in_terminal import run_in_terminal
    from prompt_toolkit.input import create_input
    from prompt_toolkit.input.vt100 import Vt100Input
    from prompt_toolkit.output.color_depth import ColorDepth
    from prompt_toolkit.styles import Style as PTStyle
    from .kitty import KittyAwareVt100Input, KittyMascot, kitty_probe

    HAS_PROMPT_TOOLKIT = True
except ImportError:
    HAS_PROMPT_TOOLKIT = False


if HAS_PROMPT_TOOLKIT:

    class SlashCommandCompleter(Completer):
        def __init__(self, commands):
            self.commands = commands

        def get_completions(self, document, complete_event):
            text = document.text_before_cursor.lstrip()
            if not text.startswith("/"):
                return
            for command, description in self.commands:
                if command.startswith(text):
                    yield Completion(command, start_position=-len(text), display_meta=description)

else:

    class SlashCommandCompleter:
        def __init__(self, commands):
            self.commands = commands

        def get_completions(self, document, complete_event):
            return


class TerminalSize:
    """Detecta tamanho do terminal e adapta pequenos detalhes."""

    @staticmethod
    def get_width() -> int:
        try:
            return shutil.get_terminal_size().columns
        except OSError:
            return 80

    @staticmethod
    def is_small() -> bool:
        return TerminalSize.get_width() < 90

    @staticmethod
    def is_tiny() -> bool:
        return TerminalSize.get_width() < 62


def ellipsize(value: str, limit: int) -> str:
    if limit <= 0:
        return ""
    if len(value) <= limit:
        return value
    if limit <= 1:
        return value[:limit]
    return value[: limit - 1] + "…"


class ZerocodingTUI:
    """Terminal UI minimalista e responsiva."""

    def __init__(
        self,
        provider_name: str = "openai",
        model: str = "gpt-4o-mini",
        theme: str = "dark",
        mode: str = "code",
        skills: Optional[list[str]] = None,
        session_id: str = "",
        connection_status: str = "unknown",
        input_budget_tokens: int = 2048,
        max_tool_steps: int = 6,
        output_budget_tokens: int = 512,
        startup_notice: str = "",
        permission_mode: str = "manual",
    ):
        if not HAS_RICH:
            raise RuntimeError("ZeroCoding TUI requires rich. Install project dependencies before starting the TUI.")

        self.provider_name = provider_name
        self.model = model
        self.theme = theme
        self.mode = mode
        self.permission_mode = permission_mode
        self.input_budget_tokens = input_budget_tokens
        self.max_tool_steps = max_tool_steps
        self.output_budget_tokens = output_budget_tokens
        self.startup_notice = startup_notice
        self.skills = skills or []
        self.session_id = session_id
        self.connection_status = connection_status
        self.pet_state = "idle"
        self.history: List[Dict[str, Any]] = []
        self.console = Console(force_terminal=True, color_system="truecolor", highlight=False, force_interactive=True)
        self.commands = COMMANDS
        self._turn_count = 0
        self._start_time = time.time()
        self._is_small = TerminalSize.is_small()
        self._is_tiny = TerminalSize.is_tiny()
        self._prompt_session = None
        self._kitty_mascot = None
        self._kitty_mascot_loaded = False
        self.last_metrics = {}
        self._full_screen = False
        self._event_queue = None
        self._cancel_event = None
        self._save_session_callback = None
        self._wizard = None
        self._pending_approval = None

        if HAS_PROMPT_TOOLKIT:
            self._setup_prompt_toolkit()

    def _refresh_size(self):
        self._is_small = TerminalSize.is_small()
        self._is_tiny = TerminalSize.is_tiny()
        return TerminalSize.get_width()

    def _setup_prompt_toolkit(self):
        kb = KeyBindings()

        @kb.add("c-j")
        def insert_newline(event):
            event.current_buffer.insert_text("\n")

        pt_style = PTStyle.from_dict(
            {
                "prompt": f"{ZERO_PURPLE} bold",
                "completion-menu.completion": f"bg:{ZERO_BG} {ZERO_LIGHT}",
                "completion-menu.completion.current": f"bg:{ZERO_USER_BG} {ZERO_LIGHT} bold",
                "completion-menu.meta.completion": f"bg:{ZERO_BG} {ZERO_GRAY}",
                "bottom-toolbar": f"bg:{ZERO_DARK} {ZERO_GRAY}",
            }
        )

        self._prompt_session = PromptSession(
            history=InMemoryHistory(),
            completer=SlashCommandCompleter(self.commands),
            complete_while_typing=True,
            style=pt_style,
            key_bindings=kb,
            multiline=False,
            refresh_interval=0.35,
        )

    def run(self, on_submit):
        """Persistent full-screen host; provider work runs on a worker thread."""
        if not HAS_PROMPT_TOOLKIT:
            while True:
                value = self.input_prompt()
                if not value or value == "/exit":
                    return
                if value:
                    on_submit(value)

        from prompt_toolkit.application.current import get_app

        self._full_screen = True
        self._event_queue = queue.Queue()
        self._transcript = []
        self._busy = False
        self._prompt_buffer = Buffer(completer=SlashCommandCompleter(self.commands), complete_while_typing=False)
        self._event_loop = None
        self._exit = False
        self._exit_output = ""
        self._kitty_mascot = None
        self._kitty_mascot_loaded = False

        def terminal_write(data):
            sys.stdout.write(data)
            sys.stdout.flush()

        app_input = None
        if os.name == "posix" and sys.stdin.isatty() and sys.stdout.isatty():
            candidate = create_input()
            if isinstance(candidate, Vt100Input):
                app_input = KittyAwareVt100Input(candidate.stdin)
                supported, buffered = kitty_probe(app_input, terminal_write)
                encoding = app_input.stdin.encoding or "utf-8"
                app_input.feed_raw(buffered.decode(encoding, errors="replace"))
                if supported:
                    self._kitty_mascot = KittyMascot()

        keys = KeyBindings()

        @keys.add("enter")
        def submit(event):
            value = self._prompt_buffer.text.strip()
            self._prompt_buffer.reset()
            if self._pending_approval:
                _, _, future = self._pending_approval
                self._pending_approval = None
                if not future.done():
                    future.set_result(value.lower() in {"s", "sim", "y", "yes"})
                self.pet_state = "thinking"
            elif self._wizard:
                self._answer_wizard(value)
            elif value:
                if value.startswith("/"):
                    if self._busy and value.split()[0].lower() not in {"/exit", "/quit", "/q"}:
                        self._transcript.append(("error", "Conclua ou cancele a geração antes de executar comandos."))
                        event.app.invalidate()
                        return
                    if self._busy and self._cancel_event:
                        self._cancel_event.set()
                        cancel = getattr(self._agent.provider, "cancel", None)
                        if cancel:
                            cancel()
                    async def command():
                        def execute_command():
                            output = io.StringIO()
                            previous_console = self.console
                            self.console = Console(
                                file=output,
                                force_terminal=False,
                                highlight=False,
                                width=max(20, TerminalSize.get_width()),
                            )
                            try:
                                on_submit(value)
                            except Exception as exc:
                                self.show_error(str(exc))
                            finally:
                                self.console = previous_console
                            return output.getvalue().rstrip()

                        rendered = await run_in_terminal(execute_command, in_executor=True)
                        if rendered:
                            if self._exit:
                                self._exit_output = rendered
                            else:
                                self._transcript.append(("command", rendered))
                                event.app.invalidate()
                        if self._exit:
                            event.app.exit()
                    event.app.create_background_task(command())
                else:
                    self._transcript.append(("user", value))
                    self._start_generation(value)
                event.app.invalidate()

        @keys.add("c-j")
        def newline(event):
            self._prompt_buffer.insert_text("\n")

        @keys.add("tab")
        def complete(event):
            buffer = event.current_buffer
            if buffer.complete_state:
                buffer.complete_next()
            else:
                buffer.start_completion(select_first=True)

        @keys.add("c-c", eager=True, is_global=True)
        def interrupt(event):
            if self._busy and self._cancel_event:
                self._cancel_event.set()
                cancel = getattr(self._agent.provider, "cancel", None)
                if cancel:
                    cancel()
                self.pet_state = "idle"
                self._transcript.append(("activity", "Cancelando geração…"))
                if self._pending_approval:
                    _, _, future = self._pending_approval
                    self._pending_approval = None
                    if not future.done():
                        future.set_result(False)
            else:
                self._prompt_buffer.reset()
                if self._wizard:
                    self._wizard = None
                    self._transcript.append(("activity", "Configuração cancelada."))
            event.app.invalidate()

        @keys.add("c-d", eager=True, is_global=True)
        def exit_app(event):
            if self._busy and self._cancel_event:
                self._cancel_event.set()
                cancel = getattr(self._agent.provider, "cancel", None)
                if cancel:
                    cancel()
            if self._pending_approval:
                _, _, future = self._pending_approval
                if not future.done():
                    future.set_result(False)
            self._exit = True
            event.app.exit()

        @keys.add("pageup")
        def scroll_up(event):
            window = getattr(self, "_transcript_window", None)
            if window:
                self._follow_transcript = False
                window.vertical_scroll = max(0, window.vertical_scroll - max(1, event.app.output.get_size().rows - 8))
                event.app.invalidate()

        @keys.add("pagedown")
        def scroll_down(event):
            window = getattr(self, "_transcript_window", None)
            if window:
                window.vertical_scroll += max(1, event.app.output.get_size().rows - 8)
                self._follow_transcript = True
                event.app.invalidate()

        wide = Condition(lambda: get_app().output.get_size().columns >= 100)
        header = Window(FormattedTextControl(self._render_header), height=Dimension.exact(5), always_hide_cursor=True)
        transcript = Window(FormattedTextControl(self._render_transcript), wrap_lines=True, always_hide_cursor=True, scroll_offsets=None)
        self._transcript_window = transcript
        self._follow_transcript = True
        sidebar = Window(FormattedTextControl(self._render_sidebar), width=Dimension(min=26, preferred=32), wrap_lines=True, always_hide_cursor=True)
        input_window = Window(
            BufferControl(self._prompt_buffer),
            height=Dimension(min=1, preferred=2),
            wrap_lines=True,
            get_line_prefix=self._input_line_prefix,
        )
        input_label = ConditionalContainer(
            Window(FormattedTextControl(self._render_input_label), height=1, always_hide_cursor=True),
            filter=Condition(lambda: self._pending_approval is not None or self._wizard is not None),
        )
        footer = Window(FormattedTextControl(self._render_footer), height=1, always_hide_cursor=True)
        root = HSplit([
            header,
            VSplit([transcript, ConditionalContainer(sidebar, filter=wide)]),
            input_label,
            input_window,
            footer,
        ])
        layout_root = FloatContainer(
            content=root,
            floats=[
                Float(
                    content=CompletionsMenu(max_height=8),
                    xcursor=True,
                    ycursor=True,
                    attach_to_window=input_window,
                )
            ],
        )

        def after_render(application):
            mascot = self._kitty_mascot
            if mascot is None:
                return
            write = application.output.write_raw
            if not self._kitty_mascot_loaded:
                try:
                    mascot.upload(write)
                    application.output.flush()
                    self._kitty_mascot_loaded = True
                    application.invalidate()
                except (OSError, ValueError):
                    try:
                        mascot.cleanup(write)
                        application.output.flush()
                    except OSError:
                        pass
                    self._kitty_mascot = None
                    application.invalidate()
                return
            try:
                width = application.output.get_size().columns
                if width < 40:
                    mascot.stop(write)
                else:
                    mascot.update(self.pet_state, width < 62, write)
                application.output.flush()
            except (OSError, ValueError):
                try:
                    mascot.cleanup(terminal_write)
                except OSError:
                    pass
                self._kitty_mascot = None
                application.invalidate()

        app = Application(
            layout=Layout(layout_root, focused_element=input_window),
            key_bindings=keys,
            full_screen=True,
            mouse_support=False,
            refresh_interval=0.2 if self._kitty_mascot is None else None,
            input=app_input,
            color_depth=ColorDepth.TRUE_COLOR if self._kitty_mascot is not None else None,
            after_render=after_render,
            style=PTStyle.from_dict(
                {
                    "input-prompt": ZERO_PURPLE,
                    "completion-menu.completion": f"bg:{ZERO_BG} {ZERO_LIGHT}",
                    "completion-menu.completion.current": f"bg:{ZERO_USER_BG} {ZERO_LIGHT} bold",
                    "completion-menu.meta.completion": f"bg:{ZERO_BG} {ZERO_GRAY}",
                }
            ),
        )
        self._app = app

        async def poll_events():
            while not self._exit:
                changed = False
                while True:
                    try:
                        item = self._event_queue.get_nowait()
                    except queue.Empty:
                        break
                    changed = True
                    kind, data = item
                    if kind == "token":
                        if not self._transcript or self._transcript[-1][0] != "assistant_stream":
                            self._transcript.append(("assistant_stream", ""))
                        role, content = self._transcript[-1]
                        self._transcript[-1] = (role, content + data)
                    elif kind == "tool":
                        self._transcript.append(("activity", data["text"]))
                        self.pet_state = "tool" if data["phase"] == "start" else "thinking"
                    elif kind == "agent_event" and data.type == "approval_request":
                        self.pet_state = "approval"
                    elif kind == "agent_event" and data.type == "approval_result":
                        self._transcript.append(("activity", data.data.get("output", "Revisão concluída.")))
                    elif kind == "metrics":
                        self.last_metrics = data
                    elif kind == "done":
                        self._busy = False
                        self.pet_state = "done"
                        if self._save_session_callback:
                            self._save_session_callback()
                    elif kind == "cancelled":
                        self._busy = False
                        self.pet_state = "idle"
                    elif kind == "error":
                        if self._cancel_event and self._cancel_event.is_set():
                            continue
                        self._busy = False
                        self.pet_state = "error"
                        self._transcript.append(("error", data))
                if changed:
                    if self._follow_transcript:
                        size = app.output.get_size()
                        cols = max(1, size.columns - (34 if size.columns >= 100 else 0))
                        visual_lines = sum(max(1, (len(text) + cols - 1) // cols) for _, text in self._transcript)
                        transcript.vertical_scroll = max(0, visual_lines - max(1, size.rows - 8))
                    app.invalidate()
                await asyncio.sleep(0.04)

        async def run_app():
            self._event_loop = asyncio.get_running_loop()
            app.create_background_task(poll_events())
            await app.run_async()

        try:
            asyncio.run(run_app())
        finally:
            self._full_screen = False
            if self._kitty_mascot is not None:
                self._kitty_mascot.cleanup(terminal_write)
                self._kitty_mascot = None
        if self._exit_output:
            self.console.print(Text(self._exit_output))

    def _start_generation(self, prompt):
        if self._busy:
            self._transcript.append(("error", "Aguarde a geração atual ou use Ctrl-C para cancelar."))
            return
        self._busy = True
        self._cancel_event = threading.Event()
        self.pet_state = "thinking"
        def approve(tool, arguments):
            future = asyncio.run_coroutine_threadsafe(self._confirm_async(tool, arguments), self._event_loop)
            return future.result()
        def worker():
            try:
                context_started = time.perf_counter()
                context_text = self._project_context.build_context()
                context_ms = (time.perf_counter() - context_started) * 1000
                events = self._agent.run_events(
                    prompt,
                    context_text=context_text,
                    approve=approve,
                    cancel_event=self._cancel_event,
                    on_event=lambda item: self._event_queue.put(("agent_event", item)),
                )
                for event in events:
                    if event.type == "token":
                        self._event_queue.put(("token", event.data["text"]))
                    elif event.type in {"tool_start", "tool_result"}:
                        name = event.data.get("name", "tool")
                        detail = event.data.get("arguments", {})
                        output = event.data.get("output", "")
                        summary = f"{name} {detail}" if event.data.get("event") == "start" else f"{name}: {output or 'ação concluída'}"
                        self._event_queue.put(("tool", {"text": summary, "phase": event.data.get("event")}))
                    elif event.type == "approval_result":
                        self._event_queue.put(("agent_event", event))
                    elif event.type == "metrics":
                        metrics = dict(event.data)
                        metrics["context_build_ms"] = round(context_ms, 1)
                        metrics["request_build_ms"] = round(metrics.get("request_build_ms", 0) + context_ms, 1)
                        for key in ("first_token_ms", "duration_ms"):
                            if metrics.get(key) is not None:
                                metrics[key] = round(metrics[key] + context_ms, 1)
                        self._event_queue.put(("metrics", metrics))
                    elif event.type == "error":
                        if not self._cancel_event.is_set():
                            self._event_queue.put(("error", event.data.get("message", "Erro")))
                    elif event.type == "done":
                        self._event_queue.put(("done", ""))
                    elif event.type == "cancelled":
                        self._event_queue.put(("cancelled", ""))
                if self._cancel_event.is_set():
                    self._event_queue.put(("cancelled", ""))
            except Exception as exc:
                self._event_queue.put(("error", str(exc)))
        threading.Thread(target=worker, daemon=True, name="zerocoding-generation").start()

    async def _confirm_async(self, tool, arguments):
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        self._pending_approval = (tool, arguments, future)
        self._transcript.append(("activity", f"Confirmar {tool.name}: {format_tool_preview(tool, arguments)} · digite s para executar"))
        self.pet_state = "approval"
        self._app.invalidate()
        return await future

    def start_wizard(self, question, on_complete, answers=None):
        self._wizard = {"question": question, "on_complete": on_complete, "answers": list(answers or [])}
        self._transcript.append(("activity", "Configuração interativa iniciada. Pressione Enter para aceitar o valor sugerido."))
        self._transcript.append(("activity", self._wizard_question()[0]))
        self._app.invalidate()

    def _wizard_question(self):
        wizard = self._wizard
        if not wizard:
            return "", ""
        return wizard["question"](len(wizard["answers"]), wizard["answers"])

    def _answer_wizard(self, answer):
        wizard = self._wizard
        label, default = self._wizard_question()
        value = answer or default
        wizard["answers"].append(value)
        self._transcript.append(("activity", f"{label}: {value}"))
        label, _ = self._wizard_question()
        if label:
            self._transcript.append(("activity", label))
        else:
            self._wizard = None
            try:
                provider, message = wizard["on_complete"](wizard["answers"])
                if provider is not None:
                    self._agent.provider = provider
                self.model = getattr(self._agent.provider, "model", self.model)
                self._transcript.append(("activity", message))
                if self._save_session_callback:
                    self._save_session_callback()
            except Exception as exc:
                self._transcript.append(("error", str(exc)))
        self._app.invalidate()

    def bind_runtime(self, agent, project_context, save_session=None):
        self._agent = agent
        self._project_context = project_context
        self._save_session_callback = save_session

    def _render_header(self):
        app = getattr(self, "_app", None)
        width = app.output.get_size().columns if app is not None else shutil.get_terminal_size().columns
        compact = width < 62
        sprite_visible = width >= 40
        mascot = getattr(self, "_kitty_mascot", None)
        if sprite_visible and mascot is not None and getattr(self, "_kitty_mascot_loaded", False):
            sprite = mascot.placeholder(self.pet_state, compact=compact)
        elif sprite_visible:
            sprite = render_mascot(self.pet_state, compact=compact, frame=int(time.monotonic() * 5))
        else:
            sprite = []
        sprite_width = 6 if compact else 8
        fallback_prefix = f"{self._pet_face(animated=True)} " if not sprite_visible else ""
        text_offset = sprite_width + 2 if sprite_visible else len(fallback_prefix)
        title = f"ZeroCoding · {self._pet_state_label()}  {self.mode}"
        details = f"{self.provider_name}/{self.model}" if compact else f"{self.provider_name} · {self.model} · {self.mode} · permissão {self.permission_mode} · sessão {self.session_id or 'nova'}"
        available = max(1, width - text_offset)
        title = ellipsize(title, available)
        details = ellipsize(details, available)
        rendered = []
        row_count = 4
        for row_index in range(row_count):
            if sprite_visible and row_index < len(sprite):
                rendered.extend(sprite[row_index])
                rendered.append(("", "  "))
            elif row_index == 0:
                rendered.append((f"bold {ZERO_PURPLE_LIGHT}", fallback_prefix))
            if row_index == 0:
                rendered.append((f"bold {ZERO_PURPLE_LIGHT}", title))
            elif row_index == 1:
                rendered.append((ZERO_GRAY, details))
            if row_index < row_count - 1:
                rendered.append(("", "\n"))
        rendered.extend((("", "\n"), ("", "─" * max(1, width))))
        return rendered

    def _render_transcript(self):
        rows = []
        if not self._transcript:
            rows.extend([(f"bold {ZERO_LIGHT}", "Bem-vindo ao ZeroCoding\n"), (ZERO_GRAY, "Digite uma tarefa ou /help. Ctrl-C cancela; Ctrl-D encerra.\n\n")])
            if self.startup_notice:
                rows.append((f"bold {ZERO_YELLOW}", f"! {self.startup_notice}\n\n"))
        for role, content in self._transcript:
            style, prefix = {"user": (f"bold {ZERO_LIGHT}", "> "), "assistant_stream": (ZERO_LIGHT, "• "), "activity": (ZERO_GRAY, "  · "), "command": (ZERO_LIGHT, ""), "error": (f"bold {ZERO_RED}", "! ")}.get(role, (ZERO_LIGHT, ""))
            rows.append((style, prefix + content.rstrip() + "\n\n"))
        if self._busy:
            rows.append((f"italic {ZERO_PURPLE_LIGHT}", f"{self._pet_face(animated=True)} {self._pet_state_label()}…\n"))
        return rows

    def _render_sidebar(self):
        return [
            (f"bold {ZERO_PURPLE_LIGHT}", "ZeroCoding\n\n"),
            (ZERO_LIGHT, f"Provider  {self.provider_name}\nModelo    {self.model}\nModo      {self.mode}\nPermissão {self.permission_mode}\nContexto  {self.input_budget_tokens} entrada / {self.output_budget_tokens} saída\nTools     {self.max_tool_steps} etapas\nSessão    {self.session_id or 'nova'}\n\n"),
            (ZERO_GRAY, "Atalhos\n/help comandos\n/provider add configurar\n/mode trocar perfil\n/permissions trocar segurança\n/context gerenciar\n/skills listar\n/status métricas\n/exit sair"),
        ]

    def _render_footer(self):
        if self._pending_approval:
            state = "s confirma · Enter recusa · Ctrl-C cancela"
        elif self._wizard:
            state = "configuração · Enter aceita valor · Ctrl-C cancela · Ctrl-D sair"
        else:
            state = "gerando · Ctrl-C cancela" if getattr(self, "_busy", False) else "Enter enviar · Tab completar · Ctrl-D sair"
        return [(ZERO_GRAY, state)]

    def _render_input_label(self):
        if self._pending_approval:
            label = "Executar ação? [s/N] "
        elif self._wizard:
            question, default = self._wizard_question()
            label = f"{question}" + (f" [{default}]" if default else "") + ": "
        else:
            label = "› "
        return [(f"bold {ZERO_YELLOW if self._pending_approval else ZERO_PURPLE}", label)]

    def _input_line_prefix(self, line_number: int, wrap_count: int):
        if self._pending_approval is not None or self._wizard is not None:
            return []
        prompt = "> " if line_number == 0 and wrap_count == 0 else "  "
        return [("class:input-prompt", prompt)]

    def header(self):
        """Header inicial simples, sem Header/Footer de framework."""
        self._refresh_size()
        self.console.clear()
        self.console.print()

        title = Text()
        title.append("ZeroCoding", style=f"bold {ZERO_LIGHT}")
        title.append(f" v{__version__}", style=f"dim {ZERO_GRAY}")
        self.console.print(title)

        meta = Text()
        meta.append("provider ", style=f"dim {ZERO_GRAY}")
        meta.append(self.provider_name, style=ZERO_PURPLE_LIGHT)
        meta.append("  model ", style=f"dim {ZERO_GRAY}")
        meta.append(ellipsize(self.model, 36 if self._is_small else 72), style=ZERO_LIGHT)
        meta.append("  mode ", style=f"dim {ZERO_GRAY}")
        meta.append(self.mode, style=ZERO_PURPLE_LIGHT)
        self.console.print(meta)

        state = Text()
        if self.skills:
            state.append("skill ", style=f"dim {ZERO_GRAY}")
            state.append(",".join(self.skills), style=ZERO_LIGHT)
            state.append("  ", style=f"dim {ZERO_GRAY}")
        if self.session_id:
            state.append("session ", style=f"dim {ZERO_GRAY}")
            state.append(self.session_id, style=ZERO_LIGHT)
            state.append("  ", style=f"dim {ZERO_GRAY}")
        state.append(self.connection_status, style=ZERO_GREEN if self.connection_status == "connected" else ZERO_GRAY)
        self.console.print(state)
        self.console.print(Text(f"{self._pet_face()} ZeroCoding · {self._pet_state_label()}", style=f"dim {ZERO_PURPLE_LIGHT}"))

        cwd = ellipsize(str(Path.cwd()), max(8, TerminalSize.get_width() - 8))
        path = Text()
        path.append("path ", style=f"dim {ZERO_GRAY}")
        path.append(cwd, style=f"dim {ZERO_LIGHT}")
        self.console.print(path)
        self.console.print()

    def show_welcome(self):
        width = self._refresh_size()
        if width < 90:
            self.console.print(Panel("Digite /help para ver os comandos. Use Tab para completar.", title="Bem-vindo", border_style=ZERO_PURPLE))
        else:
            pet = Text(GHOST_FULL, style=f"bold {ZERO_PURPLE}", justify="center")
            pet.append("\nFantasma • sempre por aqui", style=f"dim {ZERO_GRAY}")
            left = Panel(pet, title="ZeroCoding", border_style=ZERO_PURPLE, expand=True)
            activity = Text(f"Provider   {self.provider_name}\nModelo     {self.model}\nModo       {self.mode}\nPermissão  {self.permission_mode}\nSessão     {self.session_id or 'nova'}", style=ZERO_LIGHT)
            activity.append("\n\nDigite /help para ver os comandos.", style=f"dim {ZERO_GRAY}")
            right = Panel(
                activity,
                title="Sessão e atividade", border_style=ZERO_PURPLE, expand=True,
            )
            self.console.print(Columns([left, right], expand=True, equal=True))
        self.console.print()
        if self.startup_notice:
            self.show_warning(self.startup_notice)
            self.console.print()

    def display_message(self, role: str, content: str, is_code: bool = False):
        self.history.append({"role": role, "content": content, "is_code": is_code})

        if role == "user":
            self._render_user_message(content)
        elif role == "assistant":
            self._render_assistant_message(content, is_code)
        elif role == "error":
            self._render_error(content)

    def _render_user_message(self, content: str):
        self.console.print()
        for idx, line in enumerate(content.splitlines() or [""]):
            prefix = "> " if idx == 0 else "  "
            text = Text(prefix + line, style=f"{ZERO_LIGHT} on {ZERO_USER_BG}")
            self.console.print(Padding(text, (0, 1, 0, 0)))

    def _render_assistant_message(self, content: str, is_code: bool = False):
        self.console.print()
        bullet = Text("• ", style=f"bold {ZERO_PURPLE}")
        if is_code:
            try:
                rendered = Syntax(content, "python", theme="monokai", line_numbers=False, word_wrap=True)
            except Exception:
                rendered = Text(content, style=ZERO_LIGHT)
        else:
            try:
                rendered = Markdown(content, code_theme="monokai")
            except Exception:
                rendered = Text(content, style=ZERO_LIGHT)

        self.console.print(bullet, end="")
        self.console.print(rendered)
        self.console.print()
        self._turn_count += 1

    def _render_error(self, message: str):
        self.console.print()
        self.console.print(Text(f"! {message}", style=f"bold {ZERO_RED}"))

    def render_tool_call(self, name: str, target: str = ""):
        suffix = f"({target})" if target else "()"
        self.console.print(Text(f"● {name}{suffix}", style=ZERO_PURPLE_LIGHT))

    def render_tool_done(self):
        self.console.print(Text("  └ Ação concluída; interpretando o resultado…", style=f"dim {ZERO_GRAY}"))

    def input_prompt(self) -> str:
        self._refresh_size()
        if HAS_PROMPT_TOOLKIT and self._prompt_session is not None:
            try:
                def prompt_header():
                    self._refresh_size()
                    face = self._pet_face(animated=True)
                    state = self._pet_state_label()
                    label = f"{face} {state}" if self._is_tiny else f"{face} ZeroCoding · {state}"
                    return HTML(f'<style color="{ZERO_PURPLE_LIGHT}">{label}</style>\n<style color="{ZERO_PURPLE}">› </style>')

                def bottom():
                    self._refresh_size()
                    if self._is_tiny:
                        return HTML(f'<style color="{ZERO_GRAY}">/help /provider /model /exit</style>')
                    return HTML(f'<style color="{ZERO_GRAY}">/help /provider /model /skill /exit</style>')
                return self._prompt_session.prompt(
                    prompt_header,
                    bottom_toolbar=bottom,
                ).strip()
            except KeyboardInterrupt:
                return ""
            except EOFError:
                return "/exit"

        try:
            self.console.print(f"[bold {ZERO_PURPLE}]› [/bold {ZERO_PURPLE}]", end="", highlight=False)
            return input().strip()
        except (KeyboardInterrupt, EOFError):
            return ""

    def show_skills(self, skills: list):
        self.console.print()
        self.console.print(Text("skills", style=f"bold {ZERO_PURPLE_LIGHT}"))
        if not skills:
            self.console.print(Text("  no skills found", style=f"dim {ZERO_GRAY}"))
            return
        for skill in skills:
            description = ellipsize(skill.description, max(24, TerminalSize.get_width() - len(skill.name) - 6))
            self.console.print(Text(f"  • {skill.name}  {description}", style=ZERO_LIGHT))

    def show_help(self):
        self.console.print()
        self.console.print(Text("commands", style=f"bold {ZERO_PURPLE_LIGHT}"))
        command_width = max((len(command) for command, _ in self.commands), default=0) + 2
        for command, description in self.commands:
            line = Text("  ")
            line.append(command.ljust(command_width), style=f"bold {ZERO_PURPLE}")
            line.append(description, style=ZERO_LIGHT)
            self.console.print(line)

    def show_error(self, message: str):
        self._render_error(message)

    def show_info(self, message: str):
        self.console.print(Text(f"  {message}", style=f"dim {ZERO_GRAY}"))

    def show_success(self, message: str):
        self.console.print(Text(f"✓ {message}", style=ZERO_GREEN))

    def _pet_face(self, animated: bool = False) -> str:
        frames = GHOST_FRAMES.get(self.pet_state, GHOST_FRAMES["idle"])
        return frames[int(time.monotonic() * 2) % len(frames)] if animated else frames[0]

    def _pet_state_label(self) -> str:
        return GHOST_STATE_LABELS.get(self.pet_state, self.pet_state.replace("_", " "))

    def ask_value(self, label: str, default: str = "") -> str | None:
        """Ask one short setup question using the same input UI as the chat."""
        hint = f" [{default}]" if default else ""
        prompt = f"{label}{hint}: "
        try:
            if HAS_PROMPT_TOOLKIT and self._prompt_session:
                answer = self._prompt_session.prompt(HTML(f'<style color="{ZERO_PURPLE}">{prompt}</style>'))
            else:
                answer = input(prompt)
        except (KeyboardInterrupt, EOFError):
            self.show_info("Configuração cancelada.")
            return None
        return answer.strip() or default

    def set_pet_state(self, state: str):
        self.pet_state = state

    def confirm_tool(self, tool, arguments) -> bool:
        self.set_pet_state("approval")
        self.console.print(Panel(format_tool_preview(tool, arguments), title=f"Confirmar {tool.name}", border_style=ZERO_YELLOW))
        try:
            if HAS_PROMPT_TOOLKIT and self._prompt_session is not None:
                answer = self._prompt_session.prompt(HTML(f'<style color="{ZERO_YELLOW}">Executar esta ação? [s/N] </style>'))
            else:
                answer = input("Executar esta ação? [s/N] ")
        finally:
            self.set_pet_state("tool")
        return answer.strip().lower() in {"s", "sim", "y", "yes"}

    def tool_event(self, event, tool, arguments):
        if event == "start":
            self.set_pet_state("tool")
            self.render_tool_call(tool.name, format_tool_preview(tool, arguments))
        elif event == "done":
            self.set_pet_state("done")
            self.render_tool_done()
            self.set_pet_state("thinking")
        elif event == "denied":
            self.show_warning("Ação recusada; nada foi executado.")
            self.set_pet_state("thinking")
        else:
            self.set_pet_state("error")


    def show_warning(self, message: str):
        self.console.print(Text(f"! {message}", style=ZERO_YELLOW))

    def clear(self):
        self.history = []
        self._turn_count = 0
        self._start_time = time.time()
        if hasattr(self, "_transcript"):
            self._transcript.clear()
        self.header()
        self.show_welcome()

    def show_status(self):
        elapsed = int(time.time() - self._start_time)
        mins, secs = divmod(elapsed, 60)
        self.console.print()
        self.console.print(Text("status", style=f"bold {ZERO_PURPLE_LIGHT}"))
        self.console.print(Text(f"  provider  {self.provider_name}", style=ZERO_LIGHT))
        self.console.print(Text(f"  model     {self.model}", style=ZERO_LIGHT))
        self.console.print(Text(f"  mode      {self.mode}", style=ZERO_LIGHT))
        self.console.print(Text(f"  permission {self.permission_mode}", style=ZERO_LIGHT))
        self.console.print(Text(f"  profile   {self.input_budget_tokens} input / {self.output_budget_tokens} output tokens · {self.max_tool_steps} tool steps", style=ZERO_LIGHT))
        self.console.print(Text(f"  skills    {', '.join(self.skills) if self.skills else 'none'}", style=ZERO_LIGHT))
        self.console.print(Text(f"  session   {self.session_id or 'none'}", style=ZERO_LIGHT))
        self.console.print(Text(f"  turns     {self._turn_count}", style=ZERO_LIGHT))
        self.console.print(Text(f"  messages  {len(self.history)}", style=ZERO_LIGHT))
        self.console.print(Text(f"  uptime    {mins}:{secs:02d}", style=ZERO_LIGHT))
        if self.last_metrics:
            self.console.print(Text(f"  prompt    {self.last_metrics.get('request_build_ms', '?')} ms build · {self.last_metrics.get('input_tokens_estimated', '?')} tokens est. / {self.last_metrics.get('input_budget', '?')} budget", style=ZERO_LIGHT))
            self.console.print(Text(f"  response  {self.last_metrics.get('first_token_ms', '?')} ms first token · {self.last_metrics.get('duration_ms', '?')} ms total · {self.last_metrics.get('tool_calls', 0)} tool calls", style=ZERO_LIGHT))
            usage = self.last_metrics.get("provider_usage")
            if usage:
                self.console.print(Text(f"  provider  {usage}", style=f"dim {ZERO_GRAY}"))

    def show_cost(self):
        self.show_status()

    def goodbye(self):
        self.console.print()
        self.console.print(Text("ZeroCoding session ended.", style=f"dim {ZERO_GRAY}"))
        self.console.print()
