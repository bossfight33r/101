"""Claude через официальный SDK `anthropic`. Стриминг (длинные сценарии), adaptive thinking,
серверный fallback при отказе. Ответ — JSON в тексте, валидация Pydantic выше по стеку
(дискриминированный union сцен не выражается в JSON Schema structured outputs)."""

from __future__ import annotations

from techstudio.core import log
from techstudio.core.llm.base import LLMError

_log = log.get("llm.anthropic")


class AnthropicLLM:
    name = "anthropic"

    def __init__(
        self,
        model: str = "claude-opus-5-5",
        max_tokens: int = 16000,
        effort: str = "high",
        api_key: str | None = None,
    ):
        import anthropic

        self._anthropic = anthropic
        self.client = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()
        self.model = model
        self.max_tokens = max_tokens
        self.effort = effort

    def complete(self, *, task: str, system: str, user: str) -> str:
        a = self._anthropic
        try:
            with self.client.beta.messages.stream(
                model=self.model,
                max_tokens=self.max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
                thinking={"type": "adaptive"},
                output_config={"effort": self.effort},
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            ) as stream:
                msg = stream.get_final_message()
        except (a.BadRequestError, a.AuthenticationError, a.PermissionDeniedError) as e:
            raise LLMError(f"Anthropic {type(e).__name__}: {e}", retryable=False) from e
        except a.NotFoundError as e:
            raise LLMError(f"Anthropic: модель не найдена: {e}", retryable=False) from e
        except a.RateLimitError as e:
            raise LLMError("Anthropic rate limit", retryable=True) from e
        except a.APIStatusError as e:
            raise LLMError(f"Anthropic {e.status_code}", retryable=e.status_code >= 500) from e
        except a.APIConnectionError as e:
            raise LLMError("Anthropic: нет соединения", retryable=True) from e

        if msg.stop_reason == "refusal":
            raise LLMError("Claude отказался отвечать на запрос", retryable=False)
        if msg.stop_reason == "max_tokens":
            raise LLMError(
                "ответ обрезан по max_tokens — увеличь TS_LLM_MAX_TOKENS", retryable=False
            )
        text = "".join(b.text for b in msg.content if b.type == "text")
        _log.info("llm.done", task=task, model=msg.model, out_tokens=msg.usage.output_tokens)
        return text
