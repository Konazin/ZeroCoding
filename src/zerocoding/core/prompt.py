
from typing import List, Optional


def build_messages(user_text: str, system_prompt: str | None = None, history: list | None = None, skills: list | None = None):
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    elif skills:
        skill_text = "\n\n".join(f"Skill: {skill.name}\n{skill.description}" for skill in skills)
        messages.append({"role": "system", "content": f"You are a helpful coding assistant. Available skills:\n{skill_text}"})

    if history:
        messages.extend(history[-10:])

    messages.append({"role": "user", "content": user_text})
    return messages
