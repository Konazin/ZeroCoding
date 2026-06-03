"""
ZeroCoding TUI - prototipo experimental com Textual.

A interface principal do projeto vive em tui/app.py usando Rich + prompt_toolkit.
"""
from textual.app import App, ComposeResult
from textual.widgets import Input, Static, RichLog
from textual.containers import Container, Vertical
from textual.binding import Binding
from textual.screen import Screen
from textual import work
from rich.text import Text
from rich.panel import Panel
from rich.markdown import Markdown
from datetime import datetime
import asyncio
from typing import Optional

from ..core.agent import Agent


# ── Cores Roxo Pastel ────────────────────────────────────────────────────────
COLORS = {
    "purple": "#B8A9C9",
    "purple_light": "#D4C4E0",
    "purple_dark": "#9B8AA8",
    "amber": "#C9B8D4",
    "bg": "#1A1A1A",
    "dark": "#0D0D0D",
    "gray": "#6B7280",
    "green": "#A8D4C4",
    "blue": "#B8C9D4",
    "red": "#D4B8B8",
    "user_bg": "#1E1B2E",
    "border": "#3D3652",
}


# ── Tela Principal ────────────────────────────────────────────────────────────
class MainScreen(Screen):
    """Tela principal do ZeroCoding."""

    # Bindings de teclado
    BINDINGS = [
        Binding("ctrl+q", "quit", "Sair", show=True),
        Binding("ctrl+l", "clear_log", "Limpar", show=True),
        Binding("ctrl+h", "show_help", "Ajuda", show=True),
        Binding("tab", "focus_input", "Input", show=False),
    ]

    def compose(self) -> ComposeResult:
        """Compõe a interface."""
        # Container principal
        with Container(id="main-container"):
            # Área de chat (scrollável)
            with Vertical(id="chat-area"):
                # Header do chat
                yield Static("👻 ZeroCoding", id="chat-header")
                
                # Log de mensagens (scrollável automaticamente)
                yield RichLog(id="chat-log", highlight=True, markup=True)
            
            # Área de input
            with Vertical(id="input-area"):
                yield Input(
                    placeholder="Digite sua pergunta... (/help para comandos)",
                    id="user-input"
                )

    def on_mount(self) -> None:
        """Chamado quando a tela é montada."""
        # Foca no input
        self.query_one("#user-input", Input).focus()
        
        # Configura o log
        log = self.query_one("#chat-log", RichLog)
        log.write(
            Panel(
                "[dim]Bem-vindo ao ZeroCoding![/dim]\n"
                "Digite /help para ver os comandos disponíveis.",
                border_style=COLORS["purple"],
                title="👻 ZeroCoding"
            )
        )

    def action_clear_log(self) -> None:
        """Limpa o log de chat."""
        log = self.query_one("#chat-log", RichLog)
        log.clear()
        log.write("[dim]Chat limpo.[/dim]")

    def action_show_help(self) -> None:
        """Mostra ajuda."""
        log = self.query_one("#chat-log", RichLog)
        help_text = """
## Comandos Disponíveis

- `/help` - Mostra esta ajuda
- `/clear` - Limpa o chat
- `/skills` - Lista skills disponíveis
- `/status` - Status da sessão
- `/exit` - Sai da aplicação

**Dica:** Use `Tab` para focar no input, `Ctrl+L` para limpar.
"""
        log.write(Markdown(help_text))

    def action_focus_input(self) -> None:
        """Foca no input."""
        self.query_one("#user-input", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle input submission (Enter key)."""
        if event.input.id == "user-input":
            self.send_message()

    def send_message(self) -> None:
        """Envia mensagem para o agente."""
        input_widget = self.query_one("#user-input", Input)
        message = input_widget.value.strip()
        
        if not message:
            return
        
        # Limpa input
        input_widget.value = ""
        
        # Adiciona mensagem do usuário
        log = self.query_one("#chat-log", RichLog)
        log.write(
            Panel(
                message,
                border_style=COLORS["blue"],
                title="You",
                style=COLORS["user_bg"]
            )
        )
        
        # Processa comando
        if message.startswith("/"):
            self.handle_command(message)
        else:
            # Envia para o agente (async)
            self.process_with_agent(message)

    def handle_command(self, command: str) -> None:
        """Processa comandos."""
        cmd = command[1:].lower()
        log = self.query_one("#chat-log", RichLog)
        
        if cmd == "clear":
            self.action_clear_log()
        elif cmd == "help":
            self.action_show_help()
        elif cmd == "exit":
            self.app.exit()
        elif cmd == "skills":
            log.write("[dim]Skills: (em implementação)[/dim]")
        elif cmd == "status":
            log.write(f"[dim]Status: Online | {datetime.now().strftime('%H:%M:%S')}[/dim]")
        else:
            log.write(f"[red]Comando desconhecido: {command}[/red]")

    @work(exclusive=True)
    async def process_with_agent(self, message: str) -> None:
        """Processa mensagem com o agente (async)."""
        log = self.query_one("#chat-log", RichLog)
        
        # Mostra "pensando"
        log.write(
            Text("  ⠋ Pensando...", style=f"bold {COLORS['purple']}"),
            scroll_end=False
        )
        
        try:
            # Simula chamada ao agente (substituir pela chamada real)
            await asyncio.sleep(1)  # Simula delay
            response = f"Resposta para: {message}\n\nEm implementação..."
            
            # Remove "pensando" e mostra resposta
            log.clear()  # Simplificação - ideal seria remover só a última linha
            log.write(
                Panel(
                    Markdown(response),
                    border_style=COLORS["purple"],
                    title="👻 ZeroCoding"
                )
            )
            
        except Exception as e:
            log.write(f"[red]Erro: {e}[/red]")


# ── Aplicação Principal ──────────────────────────────────────────────────────
class ZeroCodingTextualApp(App):
    """Aplicação principal ZeroCoding com Textual."""

    TITLE = "ZeroCoding - Personal Coding Assistant"
    SUB_TITLE = "Powered by Textual"
    
    # CSS embutido
    CSS = """
    Screen {
        background: #0D0D0D;
    }
    
    #main-container {
        height: 100%;
        padding: 1;
    }
    
    #chat-area {
        height: 1fr;
        margin-bottom: 1;
        border: solid #3D3652;
        padding: 1;
    }
    
    #chat-header {
        color: #B8A9C9;
        text-align: center;
        padding: 1;
        margin-bottom: 1;
    }
    
    #chat-log {
        height: 1fr;
        background: #1A1A1A;
        border: solid #3D3652;
        padding: 1;
    }
    
    #input-area {
        height: auto;
        align: center middle;
    }
    
    #user-input {
        width: 3fr;
        border: solid #B8A9C9;
        padding: 1;
    }
    
    """

    def on_mount(self) -> None:
        """Monta a aplicação."""
        self.push_screen(MainScreen())


# ── Função main ──────────────────────────────────────────────────────────────
def run_textual_app(agent: Optional[Agent] = None):
    """Executa a aplicação Textual."""
    app = ZeroCodingTextualApp()
    if agent:
        app.agent = agent
    app.run()


if __name__ == "__main__":
    run_textual_app()
