
class Skill:
    def __init__(self, name: str, description: str, content: str):
        self.name = name
        self.description = description
        self.content = content

    def __repr__(self):
        return f"Skill(name={self.name!r}, description={self.description!r})"


def parse_skill(name: str, body: str):
    description = ""
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if stripped:
            description = stripped
            break
    return Skill(name=name, description=description or "No description", content=body)
