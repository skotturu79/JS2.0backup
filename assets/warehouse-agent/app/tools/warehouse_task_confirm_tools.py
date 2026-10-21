"""Warehouse Task Confirmation tools — SAP RFC /SCWM/RFC_TO_CONF via SOAP.

Falls back to this approach because the OData V4 ICF node for
API_WAREHOUSE_ORDER_TASK_2 is not activated on S4X-100.

FM: /SCWM/RFC_TO_CONF
  Designed for external/RFC-based TO confirmation; handles Open and In-Progress tasks.
  Imports: IV_LGNUM, IT_CONF_TU (table), each row:
    TANUM   - warehouse task number (10 chars, zero-padded)
    NISTA   - actual qty (leave blank = use planned qty)
    NDPLA   - destination bin override (optional)

REQUIRES EXPLICIT USER CONFIRMATION before calling.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from s4hana_client import Client

logger = logging.getLogger(__name__)

_SOAP_PATH = "/sap/bc/soap/rfc"
_FM = "/SCWM/TO_CONFIRM"


def _pad_task(v: str) -> str:
    # TANUM is CHAR12 in /SCWM/TO_CONF_TT — zero-pad to 12 digits
    return v.zfill(12) if v.isdigit() else v


def _build_soap_body(fm: str, params_xml: str, client: str = "100") -> str:
    # SAP SOAP RFC encoding for namespaced FMs: / → _-
    # /SCWM/TO_CONFIRM → _-SCWM_-TO_CONFIRM
    safe_name = fm.replace("/", "_-")
    return f"""<?xml version="1.0" encoding="utf-8"?>
<soapenv:Envelope
    xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/"
    xmlns:urn="urn:sap-com:document:sap:rfc:functions">
  <soapenv:Header/>
  <soapenv:Body>
    <urn:{safe_name}>
      {params_xml}
    </urn:{safe_name}>
  </soapenv:Body>
</soapenv:Envelope>"""


async def _call_rfc(s4: "Client", fm: str, params_xml: str, user_id: str | None) -> dict:
    """POST a SOAP RFC call and return parsed result dict."""
    dest = await s4.destination()
    client_kwargs, extra = await s4._client_kwargs(dest)

    import httpx
    # Determine sap-client from mandatory params
    tmp_params: dict = {}
    s4._inject_mandatory_params(dest, tmp_params)
    sap_client = tmp_params.get("sap-client", "100")

    soap_body = _build_soap_body(fm, params_xml, sap_client)

    headers = s4._base_headers(user_id)
    headers["Content-Type"] = "text/xml; charset=utf-8"
    headers["SOAPAction"] = f'"{fm}"'
    headers.update(extra)

    async with httpx.AsyncClient(**client_kwargs) as hc:
        resp = await hc.post(
            s4._build_url(dest.url, _SOAP_PATH),
            content=soap_body.encode("utf-8"),
            auth=s4._auth(dest),
            headers=headers,
            params=tmp_params,
        )

    logger.info("SOAP RFC %s → %s | params: %s", fm, resp.status_code, params_xml.replace("\n", " ")[:400])
    if resp.status_code >= 400:
        logger.error("SOAP RFC failed %s: %s", resp.status_code, resp.text[:500])
        return {"error": True, "status_code": resp.status_code, "message": resp.text[:500]}

    # Parse SOAP response for RETURN/messages
    text = resp.text
    logger.info("SOAP RFC response body: %s", text[:800])
    return {"status_code": resp.status_code, "raw": text}


def _parse_return(raw: str) -> tuple[bool, str]:
    """Extract E/A/W/S messages from SOAP RETURN table. Returns (has_error, message_text)."""
    import re
    errors, msgs = [], []
    for m in re.finditer(r"<TYPE>([^<]*)</TYPE>.*?<MESSAGE>([^<]*)</MESSAGE>", raw, re.S):
        mtype, msg = m.group(1).strip(), m.group(2).strip()
        if msg:
            msgs.append(f"[{mtype}] {msg}")
            if mtype in ("E", "A"):
                errors.append(msg)
    return bool(errors), "\n".join(msgs) if msgs else "No messages returned."


class ConfirmWarehouseTaskInput(BaseModel):
    ewm_warehouse: str = Field(description="EWM Warehouse number — pass exactly as the user says (e.g. '1710', 'PBAR', 'BAR1')")
    warehouse_task: str = Field(description="Warehouse task number (TANUM)")
    actual_quantity: float = Field(description="Actual confirmed quantity")
    unit_of_measure: str = Field(description="Unit of measure for actual quantity — use AlternativeUnit (e.g. 'PAL') if the task shows an alt qty, otherwise use BaseUnit (e.g. 'LB', 'KG')")
    destination_bin: str = Field(default="", description="Destination storage bin override (optional)")


class ConfirmWarehouseTaskExactInput(BaseModel):
    ewm_warehouse: str = Field(description="EWM Warehouse number — pass exactly as the user says (e.g. '1710', 'PBAR', 'BAR1')")
    warehouse_task: str = Field(description="Warehouse task number (TANUM)")
    destination_bin: str = Field(default="", description="Destination storage bin override (optional)")


def make_confirm_warehouse_task(s4: "Client", user_id: str | None = None) -> StructuredTool:
    async def confirm_warehouse_task(
        ewm_warehouse: str,
        warehouse_task: str,
        actual_quantity: float,
        unit_of_measure: str,
        destination_bin: str = "",
    ) -> str:
        """Confirm a warehouse task with actual quantity via /SCWM/TO_CONFIRM RFC."""
        tanum = _pad_task(warehouse_task)
        dest_bin_xml = f"<NDPLA>{destination_bin}</NDPLA>" if destination_bin else ""
        params_xml = f"""<IV_LGNUM>{ewm_warehouse}</IV_LGNUM>
<IV_COMMIT_WORK>X</IV_COMMIT_WORK>
<IT_CONF>
  <item>
    <TANUM>{tanum}</TANUM>
    <NISTA>{actual_quantity}</NISTA>
    <ALTME>{unit_of_measure}</ALTME>
    {dest_bin_xml}
  </item>
</IT_CONF>"""
        result = await _call_rfc(s4, _FM, params_xml, user_id)
        if result.get("error"):
            return f"Confirmation RFC call failed (HTTP {result.get('status_code')}): {result.get('message','')}"
        has_error, msg_text = _parse_return(result.get("raw", ""))
        if has_error:
            return f"Task confirmation failed:\n{msg_text}"
        return (
            f"Warehouse task confirmed successfully.\n"
            f"  Warehouse : {ewm_warehouse}\n"
            f"  Task      : {warehouse_task}\n"
            f"  Actual Qty: {actual_quantity} {unit_of_measure}\n"
            f"  (NISTA={actual_quantity}, ALTME={unit_of_measure})\n"
            f"  Dest Bin  : {destination_bin or '(planned bin)'}\n"
            f"  Status    : Confirmed (C)\n"
            f"  Messages  : {msg_text}"
        )

    return StructuredTool(
        name="confirm_warehouse_task",
        description=(
            "Confirm an EWM Warehouse Task with actual quantity via FM /SCWM/RFC_TO_CONF. "
            "Use when actual quantity differs from planned, or to override destination bin. "
            "IMPORTANT: if get_warehouse_tasks or get_warehouse_task_detail shows an alternative unit "
            "(e.g. '9 PAL'), use that alt qty and unit — NOT the base unit qty (e.g. 90 LB). "
            "Pass actual_quantity=alt_qty (e.g. 9) and unit_of_measure=alt_unit (e.g. 'PAL'). "
            "REQUIRES EXPLICIT USER CONFIRMATION before calling."
        ),
        args_schema=ConfirmWarehouseTaskInput,
        coroutine=confirm_warehouse_task,
    )


def make_confirm_warehouse_task_exact(s4: "Client", user_id: str | None = None) -> StructuredTool:
    async def confirm_warehouse_task_exact(
        ewm_warehouse: str,
        warehouse_task: str,
        destination_bin: str = "",
    ) -> str:
        """Confirm a warehouse task with exact (planned) quantity via /SCWM/TO_CONFIRM RFC."""
        tanum = _pad_task(warehouse_task)
        dest_bin_xml = f"<NDPLA>{destination_bin}</NDPLA>" if destination_bin else ""
        # NISTA left blank → SAP uses planned quantity automatically
        params_xml = f"""<IV_LGNUM>{ewm_warehouse}</IV_LGNUM>
<IV_COMMIT_WORK>X</IV_COMMIT_WORK>
<IT_CONF>
  <item>
    <TANUM>{tanum}</TANUM>
    {dest_bin_xml}
  </item>
</IT_CONF>"""
        result = await _call_rfc(s4, _FM, params_xml, user_id)
        if result.get("error"):
            return f"Confirmation RFC call failed (HTTP {result.get('status_code')}): {result.get('message','')}"
        has_error, msg_text = _parse_return(result.get("raw", ""))
        if has_error:
            return f"Exact task confirmation failed:\n{msg_text}"
        return (
            f"Warehouse task confirmed exactly (planned quantity).\n"
            f"  Warehouse : {ewm_warehouse}\n"
            f"  Task      : {warehouse_task}\n"
            f"  Dest Bin  : {destination_bin or '(planned bin)'}\n"
            f"  Status    : Confirmed (C)\n"
            f"  Messages  : {msg_text}"
        )

    return StructuredTool(
        name="confirm_warehouse_task_exact",
        description=(
            "Confirm an EWM Warehouse Task with exact (planned) quantity via FM /SCWM/RFC_TO_CONF. "
            "Use when actual quantity equals target — no qty input needed. "
            "REQUIRES EXPLICIT USER CONFIRMATION before calling."
        ),
        args_schema=ConfirmWarehouseTaskExactInput,
        coroutine=confirm_warehouse_task_exact,
    )
