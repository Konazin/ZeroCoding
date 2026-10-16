"""Task-based selection of tool schemas and skills (opt-in via `dynamic_context`)."""
from __future__ import annotations

import re

from .tools import READ_ONLY_TOOL_NAMES

WRITE_TOOL_NAMES = frozenset({"write_file", "edit_file"})
WRITE_HINTS = {
    "write", "edit", "create", "add", "modify", "change", "update", "fix", "implement",
    "refactor", "rename", "delete", "remove", "replace", "patch", "save", "generate",
    "escreva", "edite", "crie", "adicione", "modifique", "altere", "mude", "atualize",
    "corrija", "implemente", "refatore", "renomeie", "apague", "remova", "substitua", "salve", "gere",
}
COMMAND_HINTS = {
    "run", "execute", "test", "tests", "install", "build", "compile", "lint", "command", "shell",
    "rode", "rodar", "execute", "executar", "teste", "testes", "instale", "compile", "comando",
}
STOPWORDS = {
    "with", "that", "this", "from", "para", "como", "uma", "com", "dos", "das", "the", "and",
    "use", "usar", "uses", "para", "project", "projeto", "projects",
}

_WORD = re.compile(r"[a-zA-ZÀ-ÿ0-9_]+")


def _words(text: str) -> set[str]:
    return {word.lower() for word in _WORD.findall(text or "")}


def select_tool_schemas(text: str, schemas: list[dict]) -> list[dict]:
    """Keep read-only tools always; add write/command tools only when the request suggests them."""
    words = _words(text)
    wants_write = bool(words & WRITE_HINTS)
    wants_command = bool(words & COMMAND_HINTS)
    selected = []
    for spec in schemas:
        name = spec["function"]["name"]
        if name in READ_ONLY_TOOL_NAMES:
            selected.append(spec)
        elif name in WRITE_TOOL_NAMES and wants_write:
            selected.append(spec)
        elif name == "run_command" and wants_command:
            selected.append(spec)
        elif name not in WRITE_TOOL_NAMES | {"run_command"}:
            selected.append(spec)  # unknown tools are kept: never hide what we cannot classify
    return selected


def select_skills(text: str, skills: list) -> list:
    """Keep a skill when its name or a distinctive description word appears in the request."""
    words = _words(text)
    selected = []
    for skill in skills:
        name_words = _words(skill.name)
        description_words = {w for w in _words(getattr(skill, "description", "")) if len(w) >= 4 and w not in STOPWORDS}
        if name_words & words or description_words & words:
            selected.append(skill)
    return selected
