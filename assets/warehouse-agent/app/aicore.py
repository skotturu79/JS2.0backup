"""Resolve SAP AI Core credentials from a BTP destination and create a LangChain LLM.

Supports two deployment modes:
  1. Direct model deployment  — uses the OpenAI-compatible endpoint
     POST <dep_url>/v1/chat/completions
  2. Orchestration deployment — uses the SAP AI Core Orchestration API
     POST <dep_url>/completion  (scenarioId == "orchestration")

Resolution flow:
  1. Read BTP destination AICORE_DESTINATION_NAME (default: aicore)
  2. Extract clientId, clientSecret, tokenServiceURL, URL, AI-Resource-Group
  3. Get OAuth2 access token via client_credentials grant (cached for 9 min)
  4. Query AI Core Deployments API:
       a. If a running direct model deployment matches the model name  → ChatOpenAI
       b. If the only running deployment is the orchestration service  → AICoreOrchestrationChat
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any, Iterator, List, Optional, Sequence

import httpx
from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from langchain_openai import ChatOpenAI
from pydantic import Field

from s4hana_client import _CachedToken, _DestinationResolver, _first_binding

logger = logging.getLogger(__name__)

AICORE_DESTINATION_ENV = "AICORE_DESTINATION_NAME"
DEFAULT_AICORE_DESTINATION = "aicore"

# Cache TTLs
_CFG_TTL    = 3600.0   # 1 hour
_TOKEN_TTL  = 540.0    # 9 minutes
_DEPLOY_TTL = 300.0    # 5 minutes

# Module-level caches
_aicore_cfg: dict[str, str] | None = None
_aicore_cfg_expiry: float = 0.0
_access_token_cache: _CachedToken | None = None
_deployment_cache: dict[str, tuple[str, str, float]] = {}  # model → (url, scenario, expiry)


# ── Credential helpers ────────────────────────────────────────────────────────

async def _get_aicore_cfg(name: str) -> dict[str, str]:
    global _aicore_cfg, _aicore_cfg_expiry
    if _aicore_cfg and time.monotonic() < _aicore_cfg_expiry:
        return _aicore_cfg

    creds = _first_binding("destination") or {}
    if not creds:
        raise RuntimeError("No destination service binding in VCAP_SERVICES.")

    resolver = _DestinationResolver()
    xsuaa_tok = await resolver._xsuaa_access_token()

    uri = creds["uri"].rstrip("/")
    async with httpx.AsyncClient(timeout=20.0) as hc:
        resp = await hc.get(
            f"{uri}/destination-configuration/v1/destinations/{name}",
            headers={"Authorization": f"Bearer {xsuaa_tok}", "Accept": "application/json"},
        )
    if resp.status_code >= 400:
        raise RuntimeError(f"Destination HTTP {resp.status_code} for {name!r}: {resp.text}")

    cfg_raw = (resp.json().get("destinationConfiguration") or {})

    import re as _re
    base_url       = _re.sub(r'/v\d+/?$', '', (cfg_raw.get("URL") or "").rstrip("/"))
    client_id      = next((v for k, v in cfg_raw.items() if k == "clientId"), "")
    client_secret  = next((v for k, v in cfg_raw.items() if "Secret" in k and v), "")
    token_url      = next((v for k, v in cfg_raw.items() if k == "tokenServiceURL"), "")
    resource_group = (
        cfg_raw.get("URL.headers.AI-Resource-Group")
        or cfg_raw.get("AI_RESOURCE_GROUP")
        or "default"
    )

    if not base_url:
        raise RuntimeError(f"Destination {name!r} missing URL.")
    if not all([client_id, client_secret, token_url]):
        raise RuntimeError(f"Destination {name!r} missing OAuth fields.")

    _aicore_cfg = {
        "base_url":       base_url,
        "client_id":      client_id,
        "client_secret":  client_secret,
        "token_url":      token_url,
        "resource_group": resource_group,
    }
    _aicore_cfg_expiry = time.monotonic() + _CFG_TTL
    logger.info("AI Core cfg resolved: base=%s group=%s", base_url, resource_group)
    return _aicore_cfg


async def _get_access_token(cfg: dict[str, str]) -> str:
    global _access_token_cache
    if _access_token_cache and not _access_token_cache.expired():
        return _access_token_cache.value

    logger.info("AI Core: fetching fresh OAuth2 token")
    basic = httpx.BasicAuth(cfg["client_id"], cfg["client_secret"])
    token_endpoint = cfg["token_url"].rstrip("/") + "/oauth/token"
    async with httpx.AsyncClient(timeout=20.0) as hc:
        resp = await hc.post(
            token_endpoint,
            data={"grant_type": "client_credentials"},
            auth=basic,
            headers={"Accept": "application/json"},
        )
    resp.raise_for_status()
    token_value = resp.json()["access_token"]
    _access_token_cache = _CachedToken(token_value, time.monotonic() + _TOKEN_TTL)
    return token_value


async def _find_deployment(cfg: dict[str, str], model_name: str, tok: str) -> tuple[str, str]:
    """Return (deployment_url, scenario_id). Cached 5 min."""
    cached = _deployment_cache.get(model_name)
    if cached and time.monotonic() < cached[2]:
        return cached[0], cached[1]

    base = cfg["base_url"]
    rg   = cfg["resource_group"]
    async with httpx.AsyncClient(timeout=20.0) as hc:
        resp = await hc.get(
            f"{base}/v2/lm/deployments",
            params={"$expand": "details", "status": "RUNNING"},
            headers={"Authorization": f"Bearer {tok}", "AI-Resource-Group": rg, "Accept": "application/json"},
        )
    if resp.status_code >= 400:
        raise RuntimeError(f"AI Core deployments API {resp.status_code}: {resp.text}")

    items = resp.json().get("resources") or []

    # Prefer a direct model deployment matching the name
    for item in items:
        scenario = item.get("scenarioId", "")
        if scenario == "orchestration":
            continue
        details   = item.get("details", {}).get("resources", {}).get("backendDetails", {})
        found     = (details.get("model") or {}).get("name", "").lower()
        if found and (found in model_name.lower() or model_name.lower() in found):
            url = item["deploymentUrl"]
            _deployment_cache[model_name] = (url, scenario, time.monotonic() + _DEPLOY_TTL)
            logger.info("Direct deployment for %r: %s", model_name, url)
            return url, scenario

    # Fall back to orchestration deployment
    for item in items:
        if item.get("scenarioId") == "orchestration":
            url = item["deploymentUrl"]
            _deployment_cache[model_name] = (url, "orchestration", time.monotonic() + _DEPLOY_TTL)
            logger.info("Using orchestration deployment for %r: %s", model_name, url)
            return url, "orchestration"

    raise RuntimeError(f"No running deployment for {model_name!r} in resource group {rg!r}")


# ── Orchestration LLM wrapper ─────────────────────────────────────────────────

def _lc_to_orch_messages(messages: List[BaseMessage]) -> list[dict]:
    """Convert LangChain messages to the orchestration messages_history format."""
    out = []
    for m in messages:
        if isinstance(m, SystemMessage):
            # System messages go into the template, not history — skip here
            continue
        if isinstance(m, HumanMessage):
            content = m.content if isinstance(m.content, str) else json.dumps(m.content)
            out.append({"role": "user", "content": content})
        elif isinstance(m, AIMessage):
            msg: dict[str, Any] = {"role": "assistant", "content": m.content or ""}
            if m.tool_calls:
                msg["tool_calls"] = [
                    {
                        "id": tc["id"],
                        "type": "function",
                        "function": {"name": tc["name"], "arguments": json.dumps(tc["args"])},
                    }
                    for tc in m.tool_calls
                ]
            out.append(msg)
        elif isinstance(m, ToolMessage):
            out.append({"role": "tool", "tool_call_id": m.tool_call_id, "content": str(m.content)})
        else:
            out.append({"role": "user", "content": str(m.content)})
    return out


def _system_from_messages(messages: List[BaseMessage]) -> str | None:
    for m in messages:
        if isinstance(m, SystemMessage):
            return m.content if isinstance(m.content, str) else json.dumps(m.content)
    return None


def _parse_orch_response(data: dict) -> AIMessage:
    result = data.get("orchestration_result") or data
    choice = (result.get("choices") or [{}])[0]
    msg    = choice.get("message", {})
    content = msg.get("content") or ""

    tool_calls = []
    for tc in msg.get("tool_calls") or []:
        fn   = tc.get("function", {})
        args = fn.get("arguments", "{}")
        try:
            parsed_args = json.loads(args)
        except Exception:
            parsed_args = {"_raw": args}
        tool_calls.append({"name": fn["name"], "args": parsed_args, "id": tc.get("id", "")})

    finish   = choice.get("finish_reason", "stop")
    stop_map = {"tool_calls": "tool_calls", "stop": "stop", "length": "length"}

    if tool_calls:
        return AIMessage(content=content, tool_calls=tool_calls, response_metadata={"finish_reason": finish})
    return AIMessage(content=content, response_metadata={"finish_reason": finish})


class AICoreOrchestrationChat(BaseChatModel):
    """LangChain ChatModel backed by SAP AI Core Orchestration Service."""

    deployment_url: str
    model_name_param: str = Field(default="gpt-4.1")
    resource_group: str   = Field(default="default")
    temperature: float    = Field(default=0.0)
    max_tokens_param: Optional[int] = Field(default=None)
    _tools: list[dict]    = []
    _token_getter: Any    = None

    class Config:
        arbitrary_types_allowed = True

    @property
    def _llm_type(self) -> str:
        return "aicore-orchestration"

    def bind_tools(self, tools: Sequence[Any], **kwargs: Any) -> "AICoreOrchestrationChat":
        from langchain_core.tools import BaseTool
        raw_tools = []
        for t in tools:
            if isinstance(t, dict):
                raw_tools.append(t)
            elif isinstance(t, BaseTool):
                schema = t.args_schema.schema() if t.args_schema else {"type": "object", "properties": {}}
                raw_tools.append({"type": "function", "function": {"name": t.name, "description": t.description, "parameters": schema}})
            elif hasattr(t, "as_tool"):
                raw_tools.append(t.as_tool())
        clone = self.copy()
        clone._tools = raw_tools
        return clone

    def _get_token_sync(self) -> str:
        import asyncio
        if self._token_getter:
            return asyncio.get_event_loop().run_until_complete(self._token_getter())
        raise RuntimeError("No token getter set on AICoreOrchestrationChat")

    def _build_request(self, messages: List[BaseMessage]) -> dict:
        system_text = _system_from_messages(messages)
        history     = _lc_to_orch_messages(messages)

        template: list[dict] = []
        if system_text:
            template.append({"role": "system", "content": system_text})

        model_params: dict[str, Any] = {"temperature": self.temperature}
        if self.max_tokens_param:
            model_params["max_tokens"] = self.max_tokens_param
        if self._tools:
            model_params["tools"]       = self._tools
            model_params["tool_choice"] = "auto"

        return {
            "orchestration_config": {
                "module_configurations": {
                    "llm_module_config": {
                        "model_name":   self.model_name_param,
                        "model_params": model_params,
                    },
                    "templating_module_config": {"template": template},
                }
            },
            "messages_history": history,
            "input_params": {},
        }

    def _call_sync(self, messages: List[BaseMessage]) -> dict:
        import asyncio
        return asyncio.get_event_loop().run_until_complete(self._call_async(messages))

    async def _call_async(self, messages: List[BaseMessage]) -> dict:
        if self._token_getter is None:
            raise RuntimeError("AICoreOrchestrationChat: _token_getter not set.")
        token = await self._token_getter()
        body  = self._build_request(messages)
        async with httpx.AsyncClient(timeout=120.0) as hc:
            resp = await hc.post(
                f"{self.deployment_url}/completion",
                headers={
                    "Authorization":   f"Bearer {token}",
                    "AI-Resource-Group": self.resource_group,
                    "Content-Type":    "application/json",
                },
                json=body,
            )
        if resp.status_code >= 400:
            raise RuntimeError(f"Orchestration API {resp.status_code}: {resp.text[:500]}")
        return resp.json()

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        data = self._call_sync(messages)
        msg  = _parse_orch_response(data)
        return ChatResult(generations=[ChatGeneration(message=msg)])

    async def _agenerate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        data = await self._call_async(messages)
        msg  = _parse_orch_response(data)
        return ChatResult(generations=[ChatGeneration(message=msg)])


# ── Public factory ────────────────────────────────────────────────────────────

async def init_llm_from_destination(
    model_name: str,
    *,
    temperature: float = 0.0,
    max_tokens: int | None = None,
    destination_name: str | None = None,
) -> ChatOpenAI | AICoreOrchestrationChat:
    """Initialise and return a LangChain LLM via SAP AI Core BTP destination.

    Returns ChatOpenAI for direct model deployments, or AICoreOrchestrationChat
    for orchestration deployments (e.g. the default FGF tenant setup).
    """
    import os
    name    = destination_name or os.environ.get(AICORE_DESTINATION_ENV, DEFAULT_AICORE_DESTINATION)
    cfg     = await _get_aicore_cfg(name)
    tok     = await _get_access_token(cfg)
    dep_url, scenario = await _find_deployment(cfg, model_name, tok)

    if scenario == "orchestration":
        logger.info("Using orchestration LLM: model=%r url=%s", model_name, dep_url)
        llm = AICoreOrchestrationChat(
            deployment_url=dep_url,
            model_name_param=model_name,
            resource_group=cfg["resource_group"],
            temperature=temperature,
            max_tokens_param=max_tokens,
        )
        # Inject async token getter so the LLM can refresh tokens
        async def _token_getter() -> str:
            return await _get_access_token(cfg)
        llm._token_getter = _token_getter
        return llm

    # Direct deployment — use ChatOpenAI (OpenAI-compatible endpoint)
    kwargs: dict[str, Any] = {
        "model":           model_name,
        "temperature":     temperature,
        "openai_api_base": dep_url.rstrip("/") + "/v1",
        "openai_api_key":  tok,
        "default_headers": {"AI-Resource-Group": cfg["resource_group"]},
    }
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens
    llm = ChatOpenAI(**kwargs)
    logger.info("ChatOpenAI ready: model=%r deployment=%s", model_name, dep_url)
    return llm
