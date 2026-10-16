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

GHOST_TINY = "zc"
GHOST_SMALL = "(o ᴗ o)"
GHOST_SMALL_STATES = {
    "idle": "(o ᴗ o)",
    "approval": "(o ? o)",
    "success": "(^ ᴗ ^)",
    "error": "(x _ x)",
}
GHOST_WORK_FRAMES = (
    "◜█◉ᴗ◦█◝",
    "◜█◦ᴗ◉█◝",
)
GHOST_ASCII_FULL = (
    "       .--.      .",
    "     /      \\",
    "    |  o  o  |",
    "    |   ^    |",
    "     \\ .__. /",
    "      '----'  .",
)
GHOST_ASCII_WORK_FRAMES = ("(o ^ o)", "(o^  o)")
GHOST_FRAMES = (
    (
        "      ·       ▪",
        "    ▄████▄",
        "   ▟█ ◉  ◉ █▙",
        "   █   ᴗ    █",
        "   ▙█╲____╱█▟",
        "     ▀████▀  ·",
        "   ▪      ·",
    ),
    (
        "      ·       ▪",
        "    ▄████▄",
        "   ▟█  ◉ ◉ █▙",
        "   █    ᴗ   █",
        "   ▟█╲____╱█▙",
        "     ▀████▀  ·",
        "   ▪      ·",
    ),
)
GHOST_POSES = {
    "idle": (
        "    ▄████▄",
        "   ▟█ ◉  ◉ █▙",
        "   █   ᴗ    █",
        "   ▙█╲____╱█▟",
        "     ▀████▀",
    ),
    "approval": (
        "    ▄████▄",
        "   ▟█ ◉  ◉ █▙",
        "   █   ?    █",
        "   ▙█╲____╱█▟",
        "     ▀████▀",
    ),
    "success": (
        "    ▄████▄",
        "   ▟█ ^  ^ █▙",
        "   █   ᴗ    █",
        "   ▙█╲____╱█▟",
        "     ▀████▀",
    ),
    "error": (
        "    ▄████▄",
        "   ▟█ x  x █▙",
        "   █   _    █",
        "   ▙█╲____╱█▟",
        "     ▀████▀",
    ),
}
GHOST_FULL = "\n".join(GHOST_FRAMES[0])

WORK_PHRASES = (
    "Untangling the code…",
    "Checking the moving parts…",
    "Connecting a few dots…",
    "Sorting through the details…",
    "Giving the pieces a closer look…",
)

COMMANDS = [
    ("/help", "Show commands"),
    ("/clear", "Clear conversation"),
    ("/exit", "Exit ZeroCoding"),
    ("/provider", "List providers"),
    ("/provider use", "Switch provider"),
    ("/provider add", "Add provider"),
    ("/provider test", "Test active provider"),
    ("/provider remove", "Remove provider"),
    ("/model", "List available models"),
    ("/model list", "List available models"),
    ("/model use", "Switch model for this session"),
    ("/mode", "List configured modes"),
    ("/mode code", "Code mode · medium effort"),
    ("/mode reason", "Reason mode · high effort"),
    ("/mode fast", "Fast mode · low effort"),
    ("/mode smart", "Smart mode · high effort"),
    ("/metrics", "Show local per-turn metrics"),
    ("/plan", "Toggle read-only planning mode"),
    ("/ultrathink", "Toggle deeper analysis budget"),
    ("/effort", "Set low, medium, or high effort"),
    ("/skill", "List skills"),
    ("/skill add", "Activate a skill"),
    ("/skill remove", "Deactivate a skill"),
    ("/skill active", "Show active skills"),
    ("/skill clear", "Clear active skills"),
    ("/skills", "List skills"),
    ("/context", "Show context"),
    ("/context add", "Add a file to context"),
    ("/context remove", "Remove a file from context"),
    ("/context clear", "Clear context"),
    ("/context tree", "List context files"),
    ("/read", "Read a file into context"),
    ("/tree", "List project files"),
    ("/grep", "Search project files"),
    ("/sessions", "List sessions"),
    ("/resume", "Resume a session"),
    ("/session", "Show current session"),
    ("/new", "Start a new session"),
    ("/status", "Show full session status"),
]
