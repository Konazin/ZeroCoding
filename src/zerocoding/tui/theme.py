from zerocoding.tui.mascot import render, render_ascii

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
GHOST_SMALL = "[• •]"
GHOST_SMALL_STATES = {
    "idle": "[• •]",
    "approval": "[• •]?",
    "success": "[^ ^]",
    "error": "[x x]",
}
GHOST_WORK_FRAMES = ("╹[• •]╹", "╻[• •]╻")
GHOST_ASCII_WORK_FRAMES = ("[o o]", "[o.o]")
GHOST_ASCII_FULL = render_ascii("idle")
# Full-size animation: four 5-line frames used while the agent works.
GHOST_WORK_ART = tuple(render(f"work_{k}") for k in "abcd")
GHOST_WORK_ART_ASCII = tuple(render_ascii(f"work_{k}") for k in "abcd")
GHOST_POSES = {pose: render(pose) for pose in ("idle", "approval", "success", "error")}
GHOST_FULL = "\n".join(render("idle"))

WORK_PHRASES = (
    "Calibrating", "Pondering", "Untangling", "Tinkering", "Cogitating", "Noodling", "Sifting",
    "Mulling", "Wrangling", "Deciphering", "Assembling", "Tracing", "Weighing", "Stitching",
)
# Activity glyph, same family and cadence as the Claude Code spinner: grows, then shrinks.
SPINNER_FRAMES = ("·", "✢", "✳", "✶", "✻", "✽", "✻", "✶", "✳", "✢")
SPINNER_ASCII = ("-", "\\", "|", "/")
# One-line pet kept in the middle of the status row; legs shuffle while the agent works.
PET_IDLE = "[• •]"
PET_WORK = ("╹[• •]╹", "╻[• •]╻")
PET_ASCII = ("[o o]", "[o.o]")

COMMANDS = [
    ("/help", "Show commands"),
    ("/clear", "Clear conversation"),
    ("/exit", "Exit ZeroCoding"),
    ("/config", "Open the settings menu"),
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
    ("/sessions", "List, delete, or clear local sessions"),
    ("/sessions delete", "Delete one session after approval"),
    ("/sessions clear", "Delete inactive sessions after approval"),
    ("/mcp", "Show MCP servers and exposed tools"),
    ("/hooks", "Show configured hooks"),
    ("/plugins", "Show plugins"),
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
    ("/buddy", "Play a mascot animation"),
]
