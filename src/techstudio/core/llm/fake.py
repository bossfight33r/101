"""FakeLLM: детерминированные ответы по метке задачи. Ответ — строка или callable(system, user)."""

from __future__ import annotations

from collections.abc import Callable

Responder = str | Callable[[str, str], str]


class FakeLLM:
    name = "fake"

    def __init__(self, responses: dict[str, Responder] | None = None):
        self.responses: dict[str, Responder] = dict(responses or {})
        self.calls: list[dict] = []

    def set(self, task: str, response: Responder) -> None:
        self.responses[task] = response

    def complete(self, *, task: str, system: str, user: str) -> str:
        self.calls.append({"task": task, "system": system, "user": user})
        if task not in self.responses:
            raise KeyError(f"FakeLLM: нет ответа для задачи {task!r}")
        r = self.responses[task]
        return r(system, user) if callable(r) else r
