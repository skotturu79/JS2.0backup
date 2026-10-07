"""
mcp_proxy/main.py — HTTP proxy for sap-gdh-mcp

Exposes:
  GET  /tools            → list available MCP tools
  POST /call/{tool_name} → call a tool with JSON body args
  GET  /health           → liveness check

Auth: Bearer token via MCP_PROXY_TOKEN env var (optional — skip if blank)
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.responses import JSONResponse, Response

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

# ── Config ─────────────────────────────────────────────────────────────────────
MCP_CMD   = os.environ.get("MCP_CMD", r"node")
MCP_SCRIPT = os.environ.get("MCP_SCRIPT",
    r"C:\Users\I584630\Downloads\sap-gdh-mcp\sap-gdh-mcp-master\start.js")
MCP_CWD = os.environ.get("MCP_CWD",
    r"C:\Users\I584630\Downloads\sap-gdh-mcp\sap-gdh-mcp-master")
PROXY_TOKEN = os.environ.get("MCP_PROXY_TOKEN", "")   # blank = no auth

# ── MCP process manager ────────────────────────────────────────────────────────
class MCPBridge:
    def __init__(self):
        self._proc: asyncio.subprocess.Process | None = None
        self._lock = asyncio.Lock()
        self._pending: dict[str, asyncio.Future] = {}
        self._msg_id = 0
        self._initialized = False

    async def start(self):
        env = {**os.environ,
               "JAVA_HOME": r"C:\Users\I584630\.jdks\jbr-17.0.14",
               "TLS_REJECT_UNAUTHORIZED": "0",
               "JCO_ENABLED": "false"}
        env["PATH"] = env["JAVA_HOME"] + r"\bin;" + env.get("PATH", "")
        self._proc = await asyncio.create_subprocess_exec(
            MCP_CMD, MCP_SCRIPT,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
            cwd=MCP_CWD,
            limit=4 * 1024 * 1024,
        )
        asyncio.create_task(self._read_loop())
        asyncio.create_task(self._err_loop())
        await self._initialize()
        log.info("MCP bridge ready")

    async def stop(self):
        if self._proc:
            self._proc.terminate()
            await self._proc.wait()

    async def _send(self, method: str, params: dict) -> Any:
        async with self._lock:
            self._msg_id += 1
            msg_id = str(self._msg_id)
        payload = (json.dumps({
            "jsonrpc": "2.0", "id": msg_id,
            "method": method, "params": params
        }) + "\n").encode()
        fut: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending[msg_id] = fut
        self._proc.stdin.write(payload)
        await self._proc.stdin.drain()
        return await asyncio.wait_for(fut, timeout=120)

    async def _read_loop(self):
        while True:
            line = await self._proc.stdout.readline()
            if not line:
                break
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except Exception:
                log.debug("non-JSON stdout: %s", line[:200])
                continue
            msg_id = str(msg.get("id", ""))
            log.debug("recv id=%s method=%s", msg_id, msg.get("method", ""))
            if msg_id in self._pending:
                fut = self._pending.pop(msg_id)
                if "error" in msg:
                    fut.set_exception(RuntimeError(str(msg["error"])))
                else:
                    fut.set_result(msg.get("result"))

    async def _err_loop(self):
        while True:
            line = await self._proc.stderr.readline()
            if not line:
                break
            log.debug("MCP stderr: %s", line.decode().rstrip())

    async def _initialize(self):
        await self._send("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "mcp-proxy", "version": "1.0"},
        })
        notif = (json.dumps({
            "jsonrpc": "2.0", "method": "notifications/initialized", "params": {}
        }) + "\n").encode()
        self._proc.stdin.write(notif)
        await self._proc.stdin.drain()
        self._initialized = True

    async def list_tools(self) -> list[dict]:
        result = await self._send("tools/list", {})
        return result.get("tools", []) if result else []

    async def list_tools_full(self) -> list[dict]:
        """Return full tool objects including inputSchema (for MCP protocol)."""
        result = await self._send("tools/list", {})
        return result.get("tools", []) if result else []

    async def call_tool(self, name: str, arguments: dict) -> Any:
        result = await self._send("tools/call", {"name": name, "arguments": arguments})
        if result is None:
            return None
        content = result.get("content", [])
        texts = [c.get("text", "") for c in content if c.get("type") == "text"]
        return "\n".join(texts) if texts else result


bridge = MCPBridge()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await bridge.start()
    yield
    await bridge.stop()


app = FastAPI(title="sap-gdh-mcp HTTP Proxy", version="1.0", lifespan=lifespan)

# ── Auth ───────────────────────────────────────────────────────────────────────
security = HTTPBearer(auto_error=False)

def _check_auth(creds: HTTPAuthorizationCredentials | None = Depends(security)):
    if not PROXY_TOKEN:
        return  # auth disabled
    if not creds or creds.credentials != PROXY_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")


# ── Routes ─────────────────────────────────────────────────────────────────────
@app.get("/health")
async def health():
    return {"status": "ok", "mcp": "connected" if bridge._initialized else "starting"}


@app.get("/tools", dependencies=[Depends(_check_auth)])
async def list_tools():
    tools = await bridge.list_tools()
    return {"tools": [{"name": t["name"], "description": t.get("description", "")}
                      for t in tools]}


@app.post("/call/{tool_name}", dependencies=[Depends(_check_auth)])
async def call_tool(tool_name: str, request: Request):
    try:
        args = await request.json()
    except Exception:
        args = {}
    try:
        result = await bridge.call_tool(tool_name, args)
        return {"result": result}
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="MCP tool timed out")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── MCP Streamable HTTP transport — for Joule Desktop / Claude Desktop ─────────
async def _handle_mcp_message(msg: dict) -> dict | None:
    method = msg.get("method", "")
    msg_id = msg.get("id")
    params = msg.get("params", {}) or {}

    # Notifications have no id — no response expected
    if msg_id is None:
        return None

    def ok(result):
        return {"jsonrpc": "2.0", "id": msg_id, "result": result}

    def err(code, message):
        return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}

    if method == "initialize":
        return ok({
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "sap-gdh-mcp-proxy", "version": "1.0"},
        })

    if method == "tools/list":
        tools = await bridge.list_tools_full()
        return ok({"tools": tools})

    if method == "tools/call":
        name = params.get("name", "")
        arguments = params.get("arguments", {}) or {}
        try:
            result = await bridge.call_tool(name, arguments)
            content = [{"type": "text", "text": str(result) if result is not None else ""}]
            return ok({"content": content})
        except asyncio.TimeoutError:
            return err(-32000, "Tool timed out")
        except Exception as e:
            return err(-32000, str(e))

    return err(-32601, f"Method not found: {method}")


@app.post("/mcp")
async def mcp_endpoint(request: Request):
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    if isinstance(body, list):
        responses = [await _handle_mcp_message(m) for m in body]
        responses = [r for r in responses if r is not None]
        return Response(status_code=202) if not responses else JSONResponse(responses)

    resp = await _handle_mcp_message(body)
    if resp is None:
        return Response(status_code=202)
    return JSONResponse(resp)
