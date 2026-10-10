from pathlib import Path

from .parser import skill_metadata


def load_skills(base_path=None, project_path="."):
    package_root = Path(__file__).resolve().parents[3] / "skills"
    project_root = Path(project_path).resolve()
    roots = [
        package_root,
        Path("~/.zerocoding/skills").expanduser(),
        Path(base_path).expanduser() if base_path else project_root / "skills",
        project_root / ".zerocoding/skills",
    ]
    skills = {}
    for root in roots:
        if not root.exists():
            continue
        paths = list(root.glob("*.md")) + list(root.rglob("SKILL.md"))
        for path in sorted(set(paths)):
            if path.name == "SKILL.md":
                skill = skill_metadata(path)
            else:
                skill = skill_metadata(path, name=path.stem)
            skills[skill.name] = skill
    return list(skills.values())
