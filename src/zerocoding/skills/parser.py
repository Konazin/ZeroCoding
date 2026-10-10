
from pathlib import Path


class Skill:
    def __init__(self, name: str, description: str, content: str = "", path: str | Path | None = None):
        self.name = name
        self.description = description
        self._content = content
        self.path = Path(path) if path else None

    @property
    def content(self):
        if self.path is not None and self._content == "":
            self._content = self.path.read_text(encoding="utf-8")
            self._content = parse_skill(self.name, self._content).content
        return self._content

    def __repr__(self):
        return f"Skill(name={self.name!r}, description={self.description!r})"


def parse_skill(name: str, body: str):
    metadata = {}
    content = body.strip()

    if body.startswith("---"):
        parts = body.split("---", 2)
        if len(parts) == 3:
            _, frontmatter, content = parts
            for line in frontmatter.splitlines():
                if ":" not in line:
                    continue
                key, value = line.split(":", 1)
                metadata[key.strip()] = value.strip().strip('"').strip("'")

    skill_name = metadata.get("name", name)
    description = metadata.get("description", "")

    for line in content.splitlines():
        stripped = line.strip()
        if description or stripped.startswith("#"):
            continue
        if stripped:
            description = stripped
            break
    return Skill(name=skill_name, description=description or "No description", content=content.strip())


def skill_metadata(path: str | Path, name: str | None = None) -> Skill:
    path = Path(path)
    fallback_name = name or path.parent.name if path.name == "SKILL.md" else name or path.stem
    description = ""
    with path.open(encoding="utf-8") as file:
        first = file.readline()
        if first.strip() == "---":
            for line in file:
                if line.strip() == "---":
                    break
                if ":" in line:
                    key, value = line.split(":", 1)
                    if key.strip() == "name":
                        fallback_name = value.strip().strip("\"'") or fallback_name
                    elif key.strip() == "description":
                        description = value.strip().strip("\"'")
        elif first.strip() and not first.strip().startswith("#"):
            description = first.strip()
        if not description:
            for line in file:
                text = line.strip()
                if text and not text.startswith("#"):
                    description = text
                    break
    return Skill(fallback_name, description or "No description", path=path)
