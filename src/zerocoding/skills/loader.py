
from pathlib import Path
from importlib import resources
from .parser import parse_skill, Skill


def load_skills(base_path=None):
    if base_path is None:
        skill_dir = resources.files("zerocoding").joinpath("data").joinpath("skills")
    else:
        skill_dir = Path(base_path).expanduser()
        if not skill_dir.is_absolute():
            skill_dir = Path.cwd() / skill_dir
        if not skill_dir.is_dir() and str(base_path) == "skills":
            skill_dir = resources.files("zerocoding").joinpath("data").joinpath("skills")
    if not skill_dir.is_dir():
        return []
    skills = []
    entries = sorted((path for path in skill_dir.iterdir() if path.name.endswith(".md")), key=lambda path: path.name)
    for path in entries:
        content = path.read_text(encoding="utf-8")
        skill = parse_skill(Path(path.name).stem, content)
        if skill:
            skills.append(skill)
    return skills
