from __future__ import annotations

import json
import re
from typing import Protocol


class LLMError(RuntimeError):
    def __init__(self, message: str, retryable: bool = True):
        super().__init__(message)
        self.retryable = retryable


class LLMClient(Protocol):
    name: str

    def complete(self, *, task: str, system: str, user: str) -> str:
        """Вернуть текст ответа. task — метка задачи (script, scene, metadata, topics)."""
        ...


_FENCE = re.compile(r"```(?:json|yaml)?\s*(.*?)```", re.S)


def extract_json(text: str) -> dict | list:
    """Достаёт JSON из ответа: блок ```json``` или первый {...} / [...]."""
    m = _FENCE.search(text)
    candidate = m.group(1) if m else text
    candidate = candidate.strip()
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        pass
    starts = [i for i in (candidate.find("{"), candidate.find("[")) if i >= 0]
    if not starts:
        raise LLMError("в ответе LLM нет JSON", retryable=True)
    start = min(starts)
    closer = "}" if candidate[start] == "{" else "]"
    end = candidate.rfind(closer)
    try:
        return json.loads(candidate[start : end + 1])
    except json.JSONDecodeError as e:
        raise LLMError(f"невалидный JSON от LLM: {e}", retryable=True) from e
