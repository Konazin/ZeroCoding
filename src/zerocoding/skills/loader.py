
from pathlib import Path
from .parser import parse_skill, Skill


def load_skills(base_path=None):
    root = Path(__file__).resolve().parents[2]
    skill_dir = Path(base_path or root / "skills")
    if not skill_dir.exists():
        return []
    skills = []
    for path in sorted(skill_dir.glob("*.md")):
        content = path.read_text(encoding="utf-8")
        skill = parse_skill(path.stem, content)
        if skill:
            skills.append(skill)
    return skills
