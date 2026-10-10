PURPLE = "#A78BFA"
PURPLE_LIGHT = "#C4B5FD"
PURPLE_DARK = "#7C3AED"
AMBER = "#D8B4FE"
BG = "#111014"
DARK = "#09090B"
GRAY = "#9CA3AF"
LIGHT = "#F4F4F5"
GREEN = "#86EFAC"
BLUE = "#BAE6FD"
RED = "#FCA5A5"
YELLOW = "#FDE68A"
USER_BG = "#211827"
BORDER = "#3B2F4A"

GHOST_FULL = "\n".join((
    "      .-'''-.",
    "     /  ◕ ◕  \\",
    "    |    ᴗ    |",
    "     \\  ___  /",
    "      '-----'",
))
GHOST_FRAMES = {
    "idle": ("(ᵔᴗᵔ)", "(ᵔᴗᵔ)", "(•ᴗ•)", "(ᵔᴗᵔ)"),
    "thinking": ("(◔ᴗ◔)", "(ᵔ?ᵔ)", "(◔ᴗ◔)", "(ᵔᴗᵔ)"),
    "tool": ("(•ᴗ•)", "(◉ᴗ◉)", "(•ᴗ•)", "(•ᴗ•)"),
    "approval": ("(ᵔ!ᵔ)", "(•!•)", "(ᵔ!ᵔ)", "(•!•)"),
    "done": ("(ᵔ▽ᵔ)", "(◕▽◕)", "(ᵔ▽ᵔ)", "(ᵔᴗᵔ)"),
    "error": ("(×ᴗ×)", "(×﹏×)", "(×ᴗ×)", "(×﹏×)"),
}
GHOST_STATE_LABELS = {
    "idle": "pronto",
    "thinking": "pensando",
    "tool": "em ação",
    "approval": "aprovação",
    "done": "concluído",
    "error": "erro",
}

COMMANDS = [
    ("/help", "Mostrar comandos"),
    ("/clear", "Limpar conversa"),
    ("/exit", "Sair"),
    ("/provider", "Listar ou configurar providers"),
    ("/provider use", "Trocar provider"),
    ("/provider add", "Adicionar provider com assistente interativo"),
    ("/provider test", "Testar provider ativo"),
    ("/provider remove", "Remover provider"),
    ("/model", "Listar modelos"),
    ("/model list", "Listar modelos"),
    ("/model use", "Trocar modelo"),
    ("/mode", "Listar modos"),
    ("/mode code", "Modo codigo"),
    ("/mode reason", "Modo raciocinio"),
    ("/mode fast", "Modo rapido"),
    ("/mode smart", "Modo inteligente"),
    ("/permissions", "Ver modo de permissao"),
    ("/permissions manual", "Confirmar cada acao"),
    ("/permissions approve-for-me", "Revisor aprova acoes locais"),
    ("/permissions full-access", "Acesso local sem prompts (sandbox)"),
    ("/skill", "Listar skills"),
    ("/skill add", "Ativar skill"),
    ("/skill remove", "Desativar skill"),
    ("/skill active", "Listar skills ativas"),
    ("/skill clear", "Limpar skills ativas"),
    ("/skills", "Listar skills"),
    ("/mcp", "Listar servidores MCP"),
    ("/mcp tools", "Listar tools MCP"),
    ("/context", "Ver contexto"),
    ("/context add", "Adicionar arquivo ao contexto"),
    ("/context remove", "Remover arquivo do contexto"),
    ("/context clear", "Limpar contexto"),
    ("/context tree", "Listar contexto"),
    ("/read", "Ler arquivo e adicionar ao contexto"),
    ("/tree", "Listar arquivos do projeto"),
    ("/grep", "Buscar no projeto"),
    ("/sessions", "Listar sessoes"),
    ("/resume", "Retomar sessao"),
    ("/session", "Mostrar sessao atual"),
    ("/new", "Nova sessao"),
    ("/status", "Mostrar status"),
]
