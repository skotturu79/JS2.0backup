"""Utility functions for MCP tool processing."""
import asyncio
import hashlib
import logging
import os
import re
from typing import Any

import httpx
from langchain_core.tools import ToolException

logger = logging.getLogger(__name__)

_MCP_RETRY_ATTEMPTS = 4
_MCP_RETRY_DELAY = 4.0
MCP_MAX_RESPONSE_CHARS = int(os.environ.get("MCP_MAX_RESPONSE_CHARS", 100_000))


def _is_retryable_error(exc: Exception) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code < 400 or exc.response.status_code >= 500
    return True


def enhance_tool_description(mcp_tool: Any) -> str:
    if mcp_tool is None:
        return ""
    server_label = getattr(mcp_tool, "fragment_name", mcp_tool.server_name)
    return f"[{server_label}] {mcp_tool.description or ''}".strip()


def enhance_tool_name(mcp_tool: Any) -> str:
    if mcp_tool is None:
        return ""
    server_name = mcp_tool.server_name
    tool_name = mcp_tool.name
    segments = server_name.split(":")
    remaining = segments[2:] if len(segments) > 2 else segments
    server_part = "_".join(remaining)
    raw = f"{server_part}__{tool_name}"
    sanitized = re.sub(r"[^a-zA-Z0-9\-_]", "_", raw)
    if len(sanitized) <= 64:
        return sanitized
    suffix = hashlib.sha256(sanitized.encode()).hexdigest()[:8]
    return f"{sanitized[:55]}_{suffix}"


async def call_mcp_tool_with_retry(agw_client: Any, mcp_tool: Any, user_token=None, **kwargs) -> str:
    if mcp_tool is None:
        raise ValueError("Tool parameter cannot be None")
    last_exc = None
    for attempt in range(1 + _MCP_RETRY_ATTEMPTS):
        try:
            call_params = {"tool": mcp_tool, **kwargs}
            if user_token is not None:
                call_params["user_token"] = user_token
            result = await agw_client.call_mcp_tool(**call_params)
            if result is None:
                raise RuntimeError(f"SDK returned None for {mcp_tool.name}")
            result_str = str(result) if result else ""
            if len(result_str) > MCP_MAX_RESPONSE_CHARS:
                result_str = result_str[:MCP_MAX_RESPONSE_CHARS] + "\n...[truncated]"
            return result_str
        except Exception as e:
            if not _is_retryable_error(e):
                raise
            last_exc = e
            if attempt < _MCP_RETRY_ATTEMPTS:
                await asyncio.sleep(_MCP_RETRY_DELAY)
    raise ToolException(
        f"Tool '{mcp_tool.name}' failed after {1 + _MCP_RETRY_ATTEMPTS} attempts: {last_exc}"
    ) from last_exc
