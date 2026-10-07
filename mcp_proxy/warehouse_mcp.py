"""
warehouse_mcp.py — MCP 2025-03-26 Streamable HTTP adapter for the CF Warehouse Agent

Implements MCP Streamable HTTP transport:
  POST /mcp  with Accept: application/json, text/event-stream
  GET  /mcp  for SSE stream (server-initiated messages)

Run: python -m uvicorn warehouse_mcp:app --port 8766 --host 0.0.0.0
Add to Joule Desktop as: http://localhost:8766/mcp
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from typing import AsyncGenerator

import httpx
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response, StreamingResponse

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

AGENT_URL = os.environ.get(
    "WAREHOUSE_AGENT_URL",
    "https://warehouse-agent.cfapps.us10-001.hana.ondemand.com/"
)

_context_id: str | None = None

TOOL_DEF = {
    "name": "ask_warehouse_agent",
    "description": (
        "Ask the SAP EWM Warehouse Agent (warehouse PBAR, plant BAR1, system D4H-200 FGF) "
        "about warehouse orders, tasks, stock, bins, resources, outbound deliveries, "
        "physical inventory, and more. Ask in plain English."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "message": {
                "type": "string",
                "description": "Natural language question or command about warehouse operations"
            }
        },
        "required": ["message"]
    }
}


async def _call_agent(message: str) -> str:
    global _context_id
    msg: dict = {
        "messageId": str(uuid.uuid4()),
        "role": "user",
        "parts": [{"type": "text", "text": message}]
    }
    if _context_id:
        msg["contextId"] = _context_id
    payload = {
        "jsonrpc": "2.0", "id": "1",
        "method": "message/send",
        "params": {"message": msg}
    }
    async with httpx.AsyncClient(timeout=90) as client:
        resp = await client.post(AGENT_URL, json=payload)
        resp.raise_for_status()
        data = resp.json()
    result = data.get("result", {})
    if result.get("contextId") and not _context_id:
        _context_id = result["contextId"]
    parts = result.get("artifacts", [{}])[0].get("parts", [])
    text = "\n".join(
        p.get("text", "") for p in parts
        if p.get("kind") == "text" or p.get("type") == "text"
    )
    return text or "(no response)"


async def _handle(msg: dict) -> dict | None:
    method = msg.get("method", "")
    msg_id = msg.get("id")
    params = msg.get("params") or {}

    if msg_id is None:
        return None  # notification — no response

    def ok(result):
        return {"jsonrpc": "2.0", "id": msg_id, "result": result}

    def err(code, text):
        return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": text}}

    if method == "initialize":
        return ok({
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "warehouse-agent-mcp", "version": "1.0"},
        })

    if method == "tools/list":
        return ok({"tools": [TOOL_DEF]})

    if method == "tools/call":
        name = params.get("name", "")
        if name != "ask_warehouse_agent":
            return err(-32601, f"Unknown tool: {name}")
        message = (params.get("arguments") or {}).get("message", "")
        if not message:
            return err(-32602, "message is required")
        try:
            text = await _call_agent(message)
            return ok({"content": [{"type": "text", "text": text}]})
        except asyncio.TimeoutError:
            return err(-32000, "Agent timed out")
        except Exception as e:
            return err(-32000, str(e))

    return err(-32601, f"Method not found: {method}")


_sessions: set[str] = set()


def _sse_body(data: dict) -> str:
    event_id = str(uuid.uuid4())
    return f"event: message\nid: {event_id}\ndata: {json.dumps(data)}\n\n"


async def _sse_stream(data: dict) -> AsyncGenerator[str, None]:
    yield _sse_body(data)


app = FastAPI(title="Warehouse Agent MCP", version="1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Mcp-Session-Id"],
)


@app.get("/mcp")
async def mcp_get(request: Request):
    """SSE stream for server-initiated messages (MCP Streamable HTTP)."""
    session_id = request.headers.get("mcp-session-id") or request.query_params.get("sessionId", "")
    if not session_id:
        return Response(status_code=400, content="No sessionId")
    async def _keep_alive():
        while True:
            yield ": keep-alive\n\n"
            await asyncio.sleep(15)
    return StreamingResponse(_keep_alive(), media_type="text/event-stream",
                             headers={"Mcp-Session-Id": session_id, "Cache-Control": "no-cache"})


@app.post("/mcp")
async def mcp_post(request: Request):
    accept = request.headers.get("accept", "")
    wants_sse = "text/event-stream" in accept

    # MCP 2025-03-26: must accept both
    if wants_sse and "application/json" not in accept:
        return JSONResponse(
            {"jsonrpc": "2.0", "id": None,
             "error": {"code": -32000, "message": "Not Acceptable: Client must accept both application/json and text/event-stream"}},
            status_code=406
        )

    try:
        body = await request.json()
    except Exception:
        return JSONResponse(
            {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}},
            status_code=400
        )

    # Assign or reuse session ID
    session_id = request.headers.get("mcp-session-id") or str(uuid.uuid4())
    _sessions.add(session_id)
    headers = {"Mcp-Session-Id": session_id, "Cache-Control": "no-cache"}

    if isinstance(body, list):
        responses = [await _handle(m) for m in body]
        responses = [r for r in responses if r is not None]
        if not responses:
            return Response(status_code=202, headers=headers)
        if wants_sse:
            async def _multi():
                for r in responses:
                    yield _sse_body(r)
            return StreamingResponse(_multi(), media_type="text/event-stream", headers=headers)
        return JSONResponse(responses, headers=headers)

    resp = await _handle(body)
    if resp is None:
        return Response(status_code=202, headers=headers)

    if wants_sse:
        return StreamingResponse(_sse_stream(resp), media_type="text/event-stream", headers=headers)
    return JSONResponse(resp, headers=headers)


@app.get("/health")
async def health():
    return {"status": "ok", "agent_url": AGENT_URL}
