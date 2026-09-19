"""LLM client wrapper — supports Groq (primary) and Gemini (via openai-compat).

Public interface (same contract regardless of provider):
  call_llm_json(system, user_message) -> dict
  call_llm_tools(system, messages, tools) -> LLMResponse
  extract_tool_calls(response) -> list[{id, name, input}]

Fails closed: any malformed/truncated output raises ValueError, which the
caller (Analyzer/Router/Reviewer/Executor) catches and converts to escalation.

Tool definitions are expected in Anthropic format (as defined in prompts.py).
This module converts them to OpenAI format internally before calling Groq.
"""
import json
import logging
from dataclasses import dataclass, field
from typing import Any, cast

from app.config import settings

logger = logging.getLogger(__name__)


# ── Response wrapper (provider-agnostic) ──────────────────────────────────────

@dataclass
class LLMResponse:
    """Normalized response from any LLM provider's tool-use API."""
    stop_reason: str          # "tool_use" | "end_turn"
    message: dict             # Full assistant message dict, ready to append to messages
    _raw: Any = field(default=None, repr=False)


# ── Provider client ───────────────────────────────────────────────────────────

def _get_client():
    provider = settings.llm_provider.lower()
    if provider == "groq":
        from groq import Groq  # type: ignore[import]
        return Groq(api_key=settings.groq_api_key), provider
    elif provider == "gemini":
        # Gemini via OpenAI-compat endpoint
        from openai import OpenAI  # type: ignore[import]
        return OpenAI(
            api_key=settings.gemini_api_key,
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        ), provider
    else:
        raise ValueError(f"Unknown LLM provider: {provider}")


def _convert_tools_to_openai(tools: list[dict]) -> list[dict]:
    """Convert Anthropic tool-schema format to OpenAI/Groq format."""
    converted = []
    for t in tools:
        converted.append({
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t.get("description", ""),
                "parameters": t.get("input_schema", {"type": "object", "properties": {}}),
            },
        })
    return converted


# ── Public API ────────────────────────────────────────────────────────────────

def _resolve_model(provider: str) -> str:
    """Resolve active model name with safe defaults for each provider."""
    model = (settings.llm_model or "").strip()
    if provider == "gemini":
        if not model or "gemini" not in model.lower() or "gemini-1.5" in model.lower():
            return "gemini-2.5-flash"
    elif provider == "groq":
        if not model or "gemini" in model.lower() or "llama-3.3" in model.lower():
            return "openai/gpt-oss-120b"
    return model


def call_llm_json(
    system_prompt: str,
    user_message: str,
    *,
    max_tokens: int = 2048,
) -> dict:
    """Call LLM and expect a JSON response (for Analyzer, Router, Reviewer stages).

    Fails closed: raises ValueError on any malformed/non-JSON response.
    """
    client, provider = _get_client()
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message},
    ]
    response = client.chat.completions.create(
        model=_resolve_model(provider),
        max_tokens=max_tokens,
        messages=cast(Any, messages),
    )

    choice = response.choices[0]

    if choice.finish_reason == "length":
        raise ValueError("model_response_truncated")

    raw_text = (choice.message.content or "").strip()
    if not raw_text:
        raise ValueError("empty_model_response")

    # Strip markdown code fences if present
    if raw_text.startswith("```"):
        lines = raw_text.split("\n")
        raw_text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

    try:
        return json.loads(raw_text)
    except json.JSONDecodeError as exc:
        logger.error("Model returned non-JSON: %s", raw_text[:500])
        raise ValueError(f"invalid_model_output_json: {exc}") from exc


def call_llm_tools(
    system_prompt: str,
    messages: list[dict],
    tools: list[dict],
    *,
    max_tokens: int = 4096,
) -> LLMResponse:
    """Call LLM with tool-use. Returns normalized LLMResponse.

    tools: Anthropic-format tool definitions (converted internally to OpenAI format).
    messages: OpenAI-format message list (do NOT include system — passed separately).

    Fails closed: raises on any SDK/network error.
    """
    client, provider = _get_client()
    openai_tools = _convert_tools_to_openai(tools)

    all_messages = [{"role": "system", "content": system_prompt}] + messages

    response = client.chat.completions.create(
        model=_resolve_model(provider),
        max_tokens=max_tokens,
        messages=cast(Any, all_messages),
        tools=cast(Any, openai_tools),
        tool_choice="auto",
    )

    choice = response.choices[0]
    finish = choice.finish_reason  # "tool_calls" | "stop" | "length"
    msg = choice.message

    # Normalize stop_reason to Anthropic-style names (used throughout executor)
    if finish == "tool_calls":
        stop_reason = "tool_use"
    elif finish == "length":
        raise ValueError("model_response_truncated")
    else:
        stop_reason = "end_turn"

    # Build the assistant message dict ready to append to conversation
    tool_calls_list = None
    if msg.tool_calls:
        tool_calls_list = [
            {
                "id": tc.id,
                "type": "function",
                "function": {
                    "name": tc.function.name,
                    "arguments": tc.function.arguments,
                },
            }
            for tc in msg.tool_calls
        ]

    message_dict: dict = {
        "role": "assistant",
        "content": msg.content,
    }
    if tool_calls_list:
        message_dict["tool_calls"] = tool_calls_list

    return LLMResponse(stop_reason=stop_reason, message=message_dict, _raw=response)


def extract_tool_calls(response: LLMResponse) -> list[dict[str, Any]]:
    """Extract all tool-use blocks from an LLMResponse, in order.

    Returns list of {id, name, input} dicts where input is already parsed.
    """
    tool_calls_raw = response.message.get("tool_calls") or []
    calls = []
    for tc in tool_calls_raw:
        raw_args = tc["function"]["arguments"]
        try:
            input_dict = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
        except json.JSONDecodeError:
            logger.error("Tool call arguments not valid JSON: %s", raw_args[:200])
            input_dict = {}
        calls.append({
            "id": tc["id"],
            "name": tc["function"]["name"],
            "input": input_dict,
        })
    return calls


def make_tool_result_message(tool_call_id: str, content: str) -> dict:
    """Build an OpenAI-format tool result message to append to the conversation."""
    return {
        "role": "tool",
        "tool_call_id": tool_call_id,
        "content": content,
    }


# ── Backward-compat aliases (so test patches still work) ─────────────────────
call_claude_json = call_llm_json
call_claude_tools = call_llm_tools
