"""Cooperative cancellation of an agent turn."""
from __future__ import annotations

import threading


class TurnCancelled(Exception):
    """Raised when the user cancels the running turn."""


class CancelToken:
    def __init__(self):
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def check(self) -> None:
        if self._event.is_set():
            raise TurnCancelled("Turn cancelled.")
