from typing import Generator
from .context import ConversationContext
from .prompt import build_messages


class Agent:
    def __init__(self, provider, memory=None, skills=None):
        self.provider = provider
        self.memory = memory
        self.skills = skills or []
        self.active_skills = []
        self.context = ConversationContext()

    def use_skill(self, name: str) -> bool:
        return self.add_skill(name)

    def add_skill(self, name: str) -> bool:
        for skill in self.skills:
            if skill.name == name:
                if skill not in self.active_skills:
                    self.active_skills.append(skill)
                return True
        return False

    def remove_skill(self, name: str) -> bool:
        before = len(self.active_skills)
        self.active_skills = [skill for skill in self.active_skills if skill.name != name]
        return len(self.active_skills) != before

    def clear_skills(self) -> None:
        self.active_skills = []

    def set_active_skills(self, names: list[str]) -> list[str]:
        self.clear_skills()
        missing = []
        for name in names:
            if not self.add_skill(name):
                missing.append(name)
        return missing

    def active_skill_names(self) -> list[str]:
        return [skill.name for skill in self.active_skills]

    def ask(self, text, system_prompt=None):
        """Pergunta não-streaming (compatibilidade)."""
        if self.memory is not None:
            self.memory.add_message("user", text)

        messages = build_messages(
            user_text=text,
            system_prompt=system_prompt,
            history=self.context.history + (self.memory.get_history() if self.memory else []),
            skills=self.active_skills,
        )

        response_text = self.provider.chat(messages=messages)

        if self.memory is not None:
            self.memory.add_message("assistant", response_text)

        self.context.add_message("user", text)
        self.context.add_message("assistant", response_text)
        return response_text

    def ask_stream(self, text, system_prompt=None) -> Generator[str, None, None]:
        """Pergunta com streaming - gera tokens um por um."""
        if self.memory is not None:
            self.memory.add_message("user", text)

        messages = build_messages(
            user_text=text,
            system_prompt=system_prompt,
            history=self.context.history + (self.memory.get_history() if self.memory else []),
            skills=self.active_skills,
        )

        full_response = []

        for token in self.provider.chat_stream(messages=messages):
            full_response.append(token)
            yield token

        response_text = "".join(full_response)

        if self.memory is not None:
            self.memory.add_message("assistant", response_text)

        self.context.add_message("user", text)
        self.context.add_message("assistant", response_text)
