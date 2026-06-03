
from typing import List, Optional


def build_messages(user_text: str, system_prompt: str | None = None, history: list | None = None, skills: list | None = None):
    messages = []
    base_prompt = system_prompt or "You are ZeroCoding, a helpful coding assistant."
    if system_prompt:
        messages.append({"role": "system", "content": base_prompt})
    if skills:
        skill_text = "\n\n".join(
            f"Skill: {skill.name}\nDescription: {skill.description}\n\n{skill.content}"
            for skill in skills
        )
        if messages and messages[0]["role"] == "system":
            messages[0]["content"] += f"\n\nActive skills:\n{skill_text}"
        else:
            messages.append({"role": "system", "content": f"{base_prompt}\n\nActive skills:\n{skill_text}"})

    if history:
        messages.extend(history[-10:])

    messages.append({"role": "user", "content": user_text})
    return messages
