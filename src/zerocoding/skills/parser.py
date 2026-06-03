
class Skill:
    def __init__(self, name: str, description: str, content: str):
        self.name = name
        self.description = description
        self.content = content

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
