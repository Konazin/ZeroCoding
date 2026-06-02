from typing import Generator
from .context import ConversationContext
from .prompt import build_messages


class Agent:
    def __init__(self, provider, memory=None, skills=None):
        self.provider = provider
        self.memory = memory
        self.skills = skills or []
        self.context = ConversationContext()

    def ask(self, text, system_prompt=None):
        """Pergunta não-streaming (compatibilidade)."""
        if self.memory is not None:
            self.memory.add_message("user", text)

        messages = build_messages(
            user_text=text,
            system_prompt=system_prompt,
            history=self.context.history + (self.memory.get_history() if self.memory else []),
            skills=self.skills,
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
            skills=self.skills,
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