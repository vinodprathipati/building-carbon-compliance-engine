from __future__ import annotations

from dataclasses import dataclass

import anthropic
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential


@dataclass
class LLMResponse:
    text: str
    input_tokens: int
    output_tokens: int


class AnthropicProvider:
    def __init__(self, api_key: str, model: str) -> None:
        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = model

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=60),
        retry=retry_if_exception_type((anthropic.RateLimitError, anthropic.APIStatusError)),
        reraise=True,
    )
    def messages_create(
        self,
        messages: list[dict],
        max_tokens: int,
        system: str | None = None,
        temperature: float = 0,
    ) -> LLMResponse:
        # This SDK version (anthropic==1.1.0) dropped `temperature` as a typed
        # top-level parameter on Messages.create(); the underlying API still
        # accepts it, so it's passed via extra_body (confirmed working).
        kwargs: dict = dict(model=self._model, max_tokens=max_tokens, messages=messages)
        if system:
            kwargs["system"] = system
        response = self._client.messages.create(**kwargs, extra_body={"temperature": temperature})
        return LLMResponse(
            text=response.content[0].text,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        )
