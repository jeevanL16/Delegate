"""Backward-compat shim — re-exports everything from llm_client.py.

All new code should import from app.agent.llm_client directly.
This file exists so any external tooling or stale imports still resolve.
"""
from app.agent.llm_client import (  # noqa: F401
    call_llm_json as call_claude_json,
    call_llm_tools as call_claude_tools,
    extract_tool_calls,
    make_tool_result_message,
    LLMResponse,
)
