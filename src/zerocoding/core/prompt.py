
# Sanity bound only; the token budget in fit_messages decides what actually stays.
MAX_HISTORY_MESSAGES = 200


def build_messages(user_text: str, system_prompt: str | None = None, history: list | None = None, skills: list | None = None):
    messages = []
    base_prompt = system_prompt or "You are ZeroCoding, a concise coding assistant. Use project tools to inspect files. Propose changes clearly; file writes and commands require user approval."
    messages.append({"role": "system", "content": base_prompt})
    if skills:
        skill_text = "\n\n".join(
            f"Skill: {skill.name}\nDescription: {skill.description}\n\n{skill.content}"
            for skill in skills
        )
        messages[0]["content"] += f"\n\nActive skills:\n{skill_text}"

    if history:
        messages.extend(history[-MAX_HISTORY_MESSAGES:])

    messages.append({"role": "user", "content": user_text})
    return messages
