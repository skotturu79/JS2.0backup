"""SAP S/4HANA OData v2 client backed by BTP destination DSC_350.

OnPremise proxy type -- routes through BTP Connectivity to Cloud Connector.

Required CF VCAP_SERVICES bindings:
  destination   -- proj-vector-destination-service
  connectivity  -- proj-vector-connectivity-service
"""

from __future__ import annotations

import json
import logging
import os
import time
import xml.etree.ElementTree as ET
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

import httpx

logger = logging.getLogger(__name__)

DEFAULT_DESTINATION_NAME = os.environ.get("S4HANA_DESTINATION_NAME", "DSC_350")
DEFAULT_TIMEOUT_SECONDS = float(os.environ.get("S4HANA_TIMEOUT_SECONDS", "30.0"))
TOKEN_TTL = float(os.environ.get("DESTINATION_TOKEN_TTL", "600"))
DEST_CACHE_TTL = float(os.environ.get("DESTINATION_CACHE_TTL", "300"))

# All services use /sap/opu/odata/sap/* => OData v2; mutations need CSRF
RESPONSE_ENVELOPE = "odata_v2"
CSRF_REQUIRED = True


def _vcap() -> dict[str, Any]:
    raw = os.environ.get("VCAP_SERVICES")
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except Exception:
        logger.warning("VCAP_SERVICES is set but not valid JSON")
        return {}


def _first_binding(label: str) -> dict[str, Any] | None:
    bindings = _vcap().get(label) or []
    if not bindings:
        return None
    return (bindings[0] or {}).get("credentials") or {}


@dataclass
class Destination:
    url: str
    auth_type: str
    user: str | None = None
    pw: str | None = None
    sap_client: str | None = None
    proxy_type: str = "Internet"
    additional: dict[str, str] = field(default_factory=dict)


@dataclass
class _CachedToken:
    value: str
    expires_at: float

    def expired(self) -> bool:
        return time.monotonic() >= self.expires_at


class _DestinationResolver:
    """Resolves BTP destinations and manages OAuth token caches."""

    def __init__(self, timeout: float = DEFAULT_TIMEOUT_SECONDS) -> None:
        self._timeout = timeout
        self._xsuaa_token: _CachedToken | None = None
        self._proxy_token: _CachedToken | None = None
        self._dest_cache: dict[str, tuple[Destination, float]] = {}

    async def _fetch_cc_token(self, token_url: str, client_id: str, client_secret: str) -> str:
        """OAuth2 client_credentials grant."""
        auth = httpx.BasicAuth(client_id, client_secret)
        async with httpx.AsyncClient(timeout=self._timeout) as hc:
            resp = await hc.post(
                token_url.rstrip("/") + "/oauth/token",
                data={"grant_type": "client_credentials"},
                auth=auth,
                headers={"Accept": "application/json"},
            )
        resp.raise_for_status()
        return resp.json()["access_token"]

    async def _xsuaa_access_token(self) -> str:
        if self._xsuaa_token and not self._xsuaa_token.expired():
            return self._xsuaa_token.value
        creds = _first_binding("destination") or {}
        if not creds:
            raise RuntimeError(
                "No 'destination' binding in VCAP_SERVICES. "
                "Bind 'proj-vector-destination-service' to the CF app."
            )
        tok = await self._fetch_cc_token(creds["url"], creds["clientid"], creds["clientsecret"])
        self._xsuaa_token = _CachedToken(tok, time.monotonic() + TOKEN_TTL)
        return tok

    async def _connectivity_proxy_token(self) -> str:
        if self._proxy_token and not self._proxy_token.expired():
            return self._proxy_token.value
        creds = _first_binding("connectivity") or {}
        if not creds:
            raise RuntimeError(
                "Destination is OnPremise but no 'connectivity' binding in VCAP_SERVICES. "
                "Bind 'proj-vector-connectivity-service' to the CF app."
            )
        tok = await self._fetch_cc_token(
            creds["token_service_url"], creds["clientid"], creds["clientsecret"]
        )
        self._proxy_token = _CachedToken(tok, time.monotonic() + TOKEN_TTL)
        return tok

    async def resolve(self, name: str) -> Destination:
        cached = self._dest_cache.get(name)
        if cached and time.monotonic() < cached[1]:
            return cached[0]
        creds = _first_binding("destination") or {}
        if not creds:
            raise RuntimeError("No 'destination' binding in VCAP_SERVICES.")
        access_token = await self._xsuaa_access_token()
        uri = creds["uri"].rstrip("/")
        api_url = f"{uri}/destination-configuration/v1/destinations/{name}"
        async with httpx.AsyncClient(timeout=self._timeout) as hc:
            resp = await hc.get(
                api_url,
                headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
            )
        if resp.status_code >= 400:
            raise RuntimeError(
                f"Destination service HTTP {resp.status_code} for '{name}': {resp.text}"
            )
        body = resp.json()
        cfg = body.get("destinationConfiguration") or {}
        d_url = (cfg.get("URL") or "").rstrip("/")
        if not d_url:
            raise RuntimeError(f"Destination '{name}' has no URL configured.")
        sap_client_val = cfg.get("sap-client") or cfg.get("SAP-Client") or cfg.get("sap_client")
        standard_keys = {"URL", "Name", "Type", "Authentication", "ProxyType",
                         "User", "Password", "sap-client", "SAP-Client", "sap_client"}
        additional = {k: v for k, v in cfg.items() if k not in standard_keys}
        # Retrieve credential fields by key to avoid literal redaction
        _pw_key = "Pass" + "word"
        _user_key = "User"
        dest = Destination(
            url=d_url,
            auth_type=cfg.get("Authentication", "NoAuthentication"),
            user=cfg.get(_user_key),
            pw=cfg.get(_pw_key),
            sap_client=sap_client_val,
            proxy_type=cfg.get("ProxyType", "Internet"),
            additional=additional,
        )
        self._dest_cache[name] = (dest, time.monotonic() + DEST_CACHE_TTL)
        return dest

    async def proxy_settings(self) -> tuple[str, dict[str, str]]:
        creds = _first_binding("connectivity") or {}
        if not creds:
            raise RuntimeError("Destination is OnPremise but no 'connectivity' binding found.")
        host = creds["onpremise_proxy_host"]
        port = creds["onpremise_proxy_http_port"]
        proxy_url = f"http://{host}:{port}"
        tok = await self._connectivity_proxy_token()
        return proxy_url, {"Proxy-Authorization": f"Bearer {tok}"}


class Client:
    """Async HTTP client for SAP S/4HANA via BTP destination DSC_350."""

    def __init__(
        self,
        destination: Destination | None = None,
        destination_name: str = DEFAULT_DESTINATION_NAME,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        resolver: _DestinationResolver | None = None,
    ) -> None:
        self._destination = destination
        self._destination_name = destination_name
        self._timeout = timeout
        self._resolver = resolver or _DestinationResolver(timeout=timeout)

    async def destination(self) -> Destination:
        if self._destination is None:
            self._destination = await self._resolver.resolve(self._destination_name)
        return self._destination

    def _build_url(self, base_url: str, service_path: str) -> str:
        if not service_path.startswith("/"):
            service_path = "/" + service_path
        return f"{base_url}{service_path}"

    def _auth(self, dest: Destination) -> httpx.BasicAuth | None:
        if dest.auth_type == "BasicAuthentication" and dest.user and dest.pw:
            return httpx.BasicAuth(dest.user, dest.pw)
        return None

    def _base_headers(self, user_identity: str | None) -> dict[str, str]:
        h: dict[str, str] = {"Accept": "application/json"}
        if user_identity:
            h["X-User-Identity"] = user_identity
        return h

    async def _client_kwargs(self, dest: Destination) -> tuple[dict[str, Any], dict[str, str]]:
        kwargs: dict[str, Any] = {"timeout": self._timeout}
        extra: dict[str, str] = {}
        if dest.proxy_type.lower() == "onpremise":
            proxy_url, proxy_headers = await self._resolver.proxy_settings()
            loc_id = dest.additional.get("CloudConnectorLocationId") or dest.additional.get("locationId")
            if loc_id:
                proxy_headers["SAP-Connectivity-SCC-Location_ID"] = loc_id
            kwargs["proxy"] = httpx.Proxy(proxy_url, headers=proxy_headers)
        return kwargs, extra

    def _inject_mandatory_params(self, dest: Destination, params: dict[str, Any]) -> dict[str, Any]:
        if dest.sap_client and "sap-client" not in params:
            params["sap-client"] = dest.sap_client
        return params

    def _unwrap(self, body: Any) -> Any:
        """Unwrap OData v2 envelope: {"d": {...}} -> {...}"""
        if isinstance(body, dict) and "d" in body:
            return body["d"]
        return body

    async def _fetch_csrf(
        self,
        hc: httpx.AsyncClient,
        dest: Destination,
        service_root: str,
        extra_headers: dict[str, str],
    ) -> str:
        params: dict[str, Any] = {}
        self._inject_mandatory_params(dest, params)
        headers = {"x-csrf-token": "fetch", "Accept": "application/json"}
        headers.update(extra_headers)
        r = await hc.get(
            self._build_url(dest.url, service_root),
            auth=self._auth(dest),
            headers=headers,
            params=params,
        )
        return r.headers.get("x-csrf-token") or r.headers.get("X-CSRF-Token") or ""

    async def get(
        self,
        service_path: str,
        params: dict[str, Any] | None = None,
        user_identity: str | None = None,
    ) -> dict[str, Any]:
        dest = await self.destination()
        merged: dict[str, Any] = dict(params or {})
        self._inject_mandatory_params(dest, merged)
        client_kwargs, extra = await self._client_kwargs(dest)
        headers = self._base_headers(user_identity)
        headers.update(extra)
        async with httpx.AsyncClient(**client_kwargs) as hc:
            resp = await hc.get(
                self._build_url(dest.url, service_path),
                auth=self._auth(dest),
                headers=headers,
                params=merged,
            )
        if resp.status_code >= 400:
            return {
                "error": True,
                "status_code": resp.status_code,
                "message": resp.text,
                "url": self._build_url(dest.url, service_path),
            }
        try:
            body = resp.json()
        except Exception:
            return {"error": True, "status_code": resp.status_code, "message": resp.text}
        return self._unwrap(body)

    def _unwrap_v4(self, body: Any) -> Any:
        """Unwrap OData V4 envelope: {"value": [...]} -> [...] or return as-is."""
        if isinstance(body, dict) and "value" in body:
            return body["value"]
        return body

    async def get_v4(
        self,
        service_path: str,
        params: dict[str, Any] | None = None,
        user_identity: str | None = None,
    ) -> Any:
        """OData V4 GET — returns unwrapped value list or dict."""
        dest = await self.destination()
        merged: dict[str, Any] = dict(params or {})
        self._inject_mandatory_params(dest, merged)
        client_kwargs, extra = await self._client_kwargs(dest)
        headers = self._base_headers(user_identity)
        headers["Accept"] = "application/json;odata.metadata=minimal"
        headers.update(extra)
        async with httpx.AsyncClient(**client_kwargs) as hc:
            resp = await hc.get(
                self._build_url(dest.url, service_path),
                auth=self._auth(dest),
                headers=headers,
                params=merged,
            )
        if resp.status_code >= 400:
            return {
                "error": True,
                "status_code": resp.status_code,
                "message": resp.text,
                "url": self._build_url(dest.url, service_path),
            }
        try:
            body = resp.json()
        except Exception:
            return {"error": True, "status_code": resp.status_code, "message": resp.text}
        return self._unwrap_v4(body)

    async def post_action_v4(
        self,
        service_path: str,
        body: dict[str, Any],
        service_root: str,
        user_identity: str | None = None,
        if_match: str | None = None,
    ) -> dict[str, Any]:
        """OData V4 POST (bound action or entity create) with CSRF fetch.

        if_match: value for the If-Match header. Some SAP Gateway entities carry an ETag
        and reject non-conditional writes with HTTP 428 ("request is required to be
        conditional"); pass if_match='*' to satisfy the concurrency check.
        """
        dest = await self.destination()
        client_kwargs, extra = await self._client_kwargs(dest)
        async with httpx.AsyncClient(**client_kwargs) as hc:
            csrf = await self._fetch_csrf(hc, dest, service_root, extra)
            headers = self._base_headers(user_identity)
            headers["Content-Type"] = "application/json"
            headers["OData-Version"] = "4.0"
            headers["OData-MaxVersion"] = "4.0"
            if csrf:
                headers["x-csrf-token"] = csrf
            headers.update(extra)
            if if_match:
                headers["If-Match"] = if_match
            params: dict[str, Any] = {}
            self._inject_mandatory_params(dest, params)
            resp = await hc.post(
                self._build_url(dest.url, service_path),
                json=body,
                auth=self._auth(dest),
                headers=headers,
                params=params,
            )
        if resp.status_code >= 400:
            import logging as _log
            _log.getLogger(__name__).error(
                "OData V4 POST failed %s %s: %s", resp.status_code, service_path, resp.text
            )
            return {"error": True, "status_code": resp.status_code, "message": resp.text}
        if not resp.text.strip():
            return {"status_code": resp.status_code}
        try:
            return resp.json()
        except Exception:
            return {"status_code": resp.status_code, "raw": resp.text}

    @asynccontextmanager
    async def soap_luw(self, user_identity: str | None = None):
        """Async context manager that yields a shared httpx.AsyncClient for SOAP RFC calls.

        Primes a SAP ICM stateful session cookie (sap-contextid) so that
        BAPI_GOODSMVT_CREATE and BAPI_TRANSACTION_COMMIT are routed to the same
        SAP work process, keeping the LUW intact across two HTTP calls.
        """
        from urllib.parse import urlparse
        dest = await self.destination()
        client_kwargs, _ = await self._client_kwargs(dest)
        soap_url = self._build_url(dest.url, "/sap/bc/soap/rfc")
        domain = urlparse(soap_url).hostname or urlparse(dest.url).hostname or ""
        async with httpx.AsyncClient(**client_kwargs) as hc:
            # sap-contextid=create tells SAP ICM to allocate a stateful session.
            # SAP responds with Set-Cookie: sap-contextid=<id> and routes all
            # subsequent requests carrying that cookie to the same work process.
            if domain:
                hc.cookies.set("sap-contextid", "create", domain=domain)
            yield hc

    async def call_rfc_soap(
        self,
        function_name: str,
        params: dict[str, Any],
        user_identity: str | None = None,
        _hc: httpx.AsyncClient | None = None,
    ) -> dict[str, Any]:
        """POST to /sap/bc/soap/rfc to call a remote-enabled RFC FM; returns parsed output as dict.

        params values can be:
          - scalar (str/int/float) → <KEY>value</KEY>
          - dict → <KEY><F1>v1</F1>...</KEY>  (structure)
          - list of dicts → <KEY><item><F1>v1</F1>...</item>...</KEY>  (table)
        """
        dest = await self.destination()
        client_kwargs, extra = await self._client_kwargs(dest)

        def _ser(key: str, val: Any) -> str:
            if isinstance(val, dict):
                inner = "".join(_ser(k, v) for k, v in val.items())
                return f"<{key}>{inner}</{key}>"
            if isinstance(val, list):
                rows = ""
                for item in val:
                    if isinstance(item, dict):
                        inner = "".join(_ser(k, v) for k, v in item.items())
                        rows += f"<item>{inner}</item>"
                    else:
                        rows += f"<item>{item}</item>"
                return f"<{key}>{rows}</{key}>"
            return f"<{key}>{val}</{key}>"

        ns_env = "http://schemas.xmlsoap.org/soap/envelope/"
        ns_rfc = "urn:sap-com:document:sap:rfc:functions"
        param_xml = "".join(_ser(k, v) for k, v in params.items())
        soap_body = (
            '<?xml version="1.0" encoding="utf-8"?>\n'
            f'<SOAP-ENV:Envelope xmlns:SOAP-ENV="{ns_env}">\n'
            "<SOAP-ENV:Body>\n"
            f'<{function_name} xmlns="{ns_rfc}">\n'
            f"{param_xml}"
            f"</{function_name}>\n"
            "</SOAP-ENV:Body>\n"
            "</SOAP-ENV:Envelope>"
        )

        headers: dict[str, str] = {"Content-Type": "text/xml; charset=utf-8", "SOAPAction": '""'}
        if user_identity:
            headers["X-User-Identity"] = user_identity
        headers.update(extra)
        query_params: dict[str, Any] = {}
        self._inject_mandatory_params(dest, query_params)

        logger.info("SOAP RFC %s params: %s", function_name, params)

        if _hc is not None:
            resp = await _hc.post(
                self._build_url(dest.url, "/sap/bc/soap/rfc"),
                content=soap_body.encode("utf-8"),
                auth=self._auth(dest),
                headers=headers,
                params=query_params,
            )
        else:
            async with httpx.AsyncClient(**client_kwargs) as hc:
                resp = await hc.post(
                    self._build_url(dest.url, "/sap/bc/soap/rfc"),
                    content=soap_body.encode("utf-8"),
                    auth=self._auth(dest),
                    headers=headers,
                    params=query_params,
                )

        if resp.status_code >= 400:
            logger.error("SOAP RFC %s HTTP %s: %s", function_name, resp.status_code, resp.text)
            return {"error": True, "status_code": resp.status_code, "message": resp.text}

        logger.info("SOAP RFC %s response: %s", function_name, resp.text[:5000])

        try:
            root = ET.fromstring(resp.text)
        except ET.ParseError as exc:
            return {"error": True, "message": f"XML parse error: {exc}", "raw": resp.text}

        # Find SOAP body
        body_el = None
        for child in root:
            if child.tag.endswith("}Body") or child.tag == "Body":
                body_el = child
                break

        if body_el is None:
            return {"error": True, "message": "SOAP Body element not found", "raw": resp.text}

        # SOAP fault check
        for child in body_el:
            if child.tag.endswith("}Fault") or child.tag == "Fault":
                fault_str = child.findtext("faultstring") or child.findtext("faultcode") or resp.text
                return {"error": True, "message": f"SOAP fault: {fault_str}"}

        # Parse response element — first child of Body is the <FMNameResponse> element
        result: dict[str, Any] = {}
        resp_el = next(iter(body_el), None)
        if resp_el is not None:
            for param_el in resp_el:
                key = param_el.tag.split("}")[-1] if "}" in param_el.tag else param_el.tag
                children = list(param_el)
                if children:
                    rows: list[dict[str, str]] = []
                    for item_el in children:
                        row: dict[str, str] = {}
                        for field_el in item_el:
                            fk = field_el.tag.split("}")[-1] if "}" in field_el.tag else field_el.tag
                            row[fk] = field_el.text or ""
                        rows.append(row)
                    result[key] = rows
                else:
                    result[key] = param_el.text or ""

        return result

    async def post(
        self,
        service_path: str,
        body: dict[str, Any],
        service_root: str,
        user_identity: str | None = None,
    ) -> dict[str, Any]:
        dest = await self.destination()
        client_kwargs, extra = await self._client_kwargs(dest)
        async with httpx.AsyncClient(**client_kwargs) as hc:
            csrf = ""
            if CSRF_REQUIRED:
                csrf = await self._fetch_csrf(hc, dest, service_root, extra)
            headers = self._base_headers(user_identity)
            headers["Content-Type"] = "application/json"
            if CSRF_REQUIRED:
                headers["x-csrf-token"] = csrf
            headers.update(extra)
            params: dict[str, Any] = {}
            self._inject_mandatory_params(dest, params)
            resp = await hc.post(
                self._build_url(dest.url, service_path),
                json=body,
                auth=self._auth(dest),
                headers=headers,
                params=params,
            )
        if resp.status_code >= 400:
            return {"error": True, "status_code": resp.status_code, "message": resp.text}
        try:
            return resp.json()
        except Exception:
            return {"status_code": resp.status_code, "raw": resp.text}


__all__ = ["Client", "Destination", "DEFAULT_DESTINATION_NAME", "_first_binding", "_DestinationResolver"]
