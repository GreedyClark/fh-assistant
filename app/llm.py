from dataclasses import dataclass
from typing import Protocol

import anthropic


class LLMError(Exception):
    def __init__(self, message: str, kind: str = "other"):
        super().__init__(message)
        self.kind = kind


def classify_api_error(exc: Exception) -> tuple[str, str]:
    """Повертає (kind, зрозумілий текст) для помилки Anthropic."""
    text = str(exc)
    if isinstance(exc, anthropic.AuthenticationError):
        return "llm_auth", "Anthropic не приймає ключ, перевір ANTHROPIC_API_KEY"
    if "credit balance" in text.lower():
        return "llm_billing", "На рахунку Anthropic закінчились кредити, поповни баланс"
    return "other", f"{type(exc).__name__}: {text}"


@dataclass
class ToolResult:
    data: dict
    model: str
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int


class LLMClient(Protocol):
    async def call_tool(
        self,
        static_blocks: list[str],
        user_text: str,
        tool_name: str,
        tool_description: str,
        schema: dict,
    ) -> ToolResult: ...


class AnthropicClient:
    def __init__(self, api_key: str, model: str, max_tokens: int):
        self._client = anthropic.AsyncAnthropic(api_key=api_key, timeout=90, max_retries=2)
        self._model = model
        self._max_tokens = max_tokens

    async def call_tool(
        self,
        static_blocks: list[str],
        user_text: str,
        tool_name: str,
        tool_description: str,
        schema: dict,
    ) -> ToolResult:
        system = [{"type": "text", "text": block} for block in static_blocks]
        system[-1]["cache_control"] = {"type": "ephemeral"}
        try:
            response = await self._client.messages.create(
                model=self._model,
                max_tokens=self._max_tokens,
                system=system,
                messages=[{"role": "user", "content": user_text}],
                tools=[{"name": tool_name, "description": tool_description, "input_schema": schema}],
                tool_choice={"type": "tool", "name": tool_name},
            )
        except anthropic.APIError as exc:
            kind, message = classify_api_error(exc)
            raise LLMError(message, kind) from exc

        if response.stop_reason == "max_tokens":
            raise LLMError("Відповідь моделі обрізана лімітом токенів")
        block = next((b for b in response.content if b.type == "tool_use"), None)
        if block is None:
            raise LLMError(f"Model returned no tool call (stop_reason={response.stop_reason})")
        usage = response.usage
        return ToolResult(
            data=dict(block.input),
            model=response.model,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cache_read_tokens=usage.cache_read_input_tokens or 0,
        )
