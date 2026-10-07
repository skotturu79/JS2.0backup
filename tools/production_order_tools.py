"""Production Order read tools — orders, components, operations, confirmations.

Read tools use BAPI calls via SOAP RFC:
  BAPI_PRODORD_GET_LIST   — list production orders (header overview)
  BAPI_PRODORD_GET_DETAIL — single order: header + components + operations

Confirmations read via OData V2 (separate service, may be active):
  API_PROD_ORDER_CONFIRMATION  /sap/opu/odata/sap/API_PROD_ORDER_CONFIRMATION
"""
from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from typing import TYPE_CHECKING, Any

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from s4hana_client import Client

from tools.warehouse_task_confirm_tools import _build_soap_body, _call_rfc

logger = logging.getLogger(__name__)

_SOAP_PATH = "/sap/bc/soap/rfc"
_CONF_SRV = "/sap/opu/odata/sap/API_PROD_ORDER_CONFIRMATION"
MAX_PAGE_SIZE = 100


# ---------------------------------------------------------------------------
# SOAP XML helpers
# ---------------------------------------------------------------------------

def _strip_ns(raw: str) -> ET.Element:
    """Parse XML, strip all namespaces from tags."""
    root = ET.fromstring(raw)
    for el in root.iter():
        if "}" in el.tag:
            el.tag = el.tag.split("}", 1)[1]
    return root


def _soap_items(raw: str, tag: str) -> list[dict]:
    """Extract <tag><item>…</item></tag> from SOAP response into list of dicts."""
    try:
        root = _strip_ns(raw)
        parent = root.find(f".//{tag}")
        if parent is None:
            return []
        result = []
        for item in parent.findall("item"):
            row = {child.tag: (child.text or "").strip() for child in item}
            result.append(row)
        return result
    except Exception as e:
        logger.error("_soap_items(%s) parse error: %s", tag, e)
        return []


def _soap_struct(raw: str, tag: str) -> dict:
    """Extract single <tag>…</tag> structure from SOAP response into dict."""
    try:
        root = _strip_ns(raw)
        parent = root.find(f".//{tag}")
        if parent is None:
            return {}
        return {child.tag: (child.text or "").strip() for child in parent}
    except Exception as e:
        logger.error("_soap_struct(%s) parse error: %s", tag, e)
        return {}


def _soap_return(raw: str) -> tuple[bool, str]:
    """Extract E/A messages from SOAP RETURN table. Returns (has_error, text)."""
    items = _soap_items(raw, "RETURN")
    errors, msgs = [], []
    for it in items:
        mtype = it.get("TYPE", "")
        msg = it.get("MESSAGE", "")
        if msg:
            msgs.append(f"[{mtype}] {msg}")
            if mtype in ("E", "A"):
                errors.append(msg)
    return bool(errors), "\n".join(msgs) if msgs else ""


def _fmt_date(d: str) -> str:
    """Convert YYYYMMDD → YYYY-MM-DD; return '-' for empty/zeros."""
    d = d.strip()
    if not d or d == "00000000":
        return "-"
    if len(d) == 8 and d.isdigit():
        return f"{d[:4]}-{d[4:6]}-{d[6:]}"
    return d


def _pad_order(v: str) -> str:
    return v.zfill(12) if v.isdigit() else v


# ---------------------------------------------------------------------------
# OData helpers (kept for get_production_confirmations)
# ---------------------------------------------------------------------------

def _fmt_params(params: dict[str, Any]) -> dict[str, Any]:
    params.setdefault("$format", "json")
    return params


def _odata_results(payload: Any) -> tuple[list[dict], str]:
    if isinstance(payload, dict):
        err = payload.get("error")
        if err:
            if err is True:
                return [], f"SAP API error (HTTP {payload.get('status_code','')}): {payload.get('message','unknown')}"
            if isinstance(err, dict):
                msg = err.get("message", {})
                text = msg.get("value", str(err)) if isinstance(msg, dict) else str(msg)
                return [], f"SAP API error [{err.get('code','')}]: {text}"
            return [], f"SAP API error: {err}"
        inner = payload.get("results", payload)
        if isinstance(inner, list):
            return inner, ""
        if isinstance(inner, dict):
            r = inner.get("results", [])
            return (r if isinstance(r, list) else []), ""
    if isinstance(payload, list):
        return payload, ""
    return [], ""


# ---------------------------------------------------------------------------
# Input schemas
# ---------------------------------------------------------------------------

class GetProductionOrderInput(BaseModel):
    production_order: str = Field(default="", description="Production order number (exact lookup)")
    plant: str = Field(default="", description="Plant code to list orders (e.g. '1710')")
    material: str = Field(default="", description="Material number filter (optional)")
    status_filter: str = Field(
        default="",
        description=(
            "Status filter: REL=Released, CNF=Confirmed, "
            "TECO=Technically completed, DLV=Delivered — leave blank for all"
        ),
    )
    top: int = Field(default=20, description="Max records when listing (max 100)")


class GetProductionOrderComponentsInput(BaseModel):
    production_order: str = Field(description="Production order number")


class GetProductionOrderOperationsInput(BaseModel):
    production_order: str = Field(description="Production order number")


class GetProductionConfirmationsInput(BaseModel):
    production_order: str = Field(description="Production order number")
    top: int = Field(default=50, description="Max records (max 100)")


# ---------------------------------------------------------------------------
# Tool factories
# ---------------------------------------------------------------------------

def make_get_production_order(s4: "Client", user_id: str | None = None) -> StructuredTool:
    async def get_production_order(
        production_order: str = "",
        plant: str = "",
        material: str = "",
        status_filter: str = "",
        top: int = 20,
    ) -> str:
        capped = min(top, MAX_PAGE_SIZE)

        # ── Single order detail ──────────────────────────────────────────────
        if production_order:
            padded = _pad_order(production_order)
            params_xml = f"<NUMBER>{padded}</NUMBER>"
            result = await _call_rfc(s4, "BAPI_PRODORD_GET_DETAIL", params_xml, user_id)
            if result.get("error"):
                return (
                    f"BAPI_PRODORD_GET_DETAIL failed "
                    f"(HTTP {result.get('status_code')}): {result.get('message','')}"
                )
            raw = result.get("raw", "")
            has_err, ret_msg = _soap_return(raw)
            if has_err:
                return f"BAPI_PRODORD_GET_DETAIL error:\n{ret_msg}"

            r = _soap_struct(raw, "ORDERDATA")
            if not r:
                return f"No data returned for production order {production_order}."

            status = r.get("SYS_STATUS", "") or r.get("STATUS", "") or "-"
            planned_qty = r.get("PLND_TOTAL_QTY", "") or r.get("BASE_QTY", "") or "-"
            unit = r.get("UNIT_NET", "") or r.get("BASE_UOM", "") or ""
            conf_qty = r.get("CONFIRMED_QTY", "") or r.get("CONF_YIELD", "") or "0"
            mat_desc = r.get("DESCRIPT", "") or r.get("MAT_DESC", "") or r.get("DESCRIPTION", "")

            lines = [
                f"Production Order: {r.get('ORDER_NUM', production_order)}",
                f"  Material     : {r.get('MATERIAL', '-')} — {mat_desc}",
                f"  Plant        : {r.get('PLANT', '-')}",
                f"  Order Type   : {r.get('ORDER_TYPE', '-')}",
                f"  Status       : {status}",
                f"  Planned Qty  : {planned_qty} {unit}",
                f"  Confirmed Qty: {conf_qty} {unit}",
                f"  Sched Start  : {_fmt_date(r.get('BASIC_START', ''))}",
                f"  Sched End    : {_fmt_date(r.get('BASIC_FIN', ''))}",
                f"  MRP Ctrl     : {r.get('MRP_CNTRLR', '-') or '-'}",
                f"  Supervisor   : {r.get('PROD_SUPV', '-') or '-'}",
            ]
            if ret_msg:
                lines.append(f"  Messages     : {ret_msg}")
            return "\n".join(lines)

        # ── List orders ──────────────────────────────────────────────────────
        if not plant:
            return "Provide either a production_order number or a plant to list orders."

        status_xml = ""
        if status_filter == "REL":
            status_xml = "<SELECTION_STATUS><RELEASED>X</RELEASED></SELECTION_STATUS>"
        elif status_filter == "CNF":
            status_xml = "<SELECTION_STATUS><CONFIRMED>X</CONFIRMED></SELECTION_STATUS>"
        elif status_filter == "TECO":
            status_xml = "<SELECTION_STATUS><TECO_FINISHED>X</TECO_FINISHED></SELECTION_STATUS>"
        elif status_filter == "DLV":
            status_xml = "<SELECTION_STATUS><DELIVERED>X</DELIVERED></SELECTION_STATUS>"

        mat_xml = f"<MATERIAL>{material}</MATERIAL>" if material else ""
        params_xml = (
            f"<PLANT>{plant}</PLANT>"
            f"{mat_xml}"
            f"<MAX_NROF_ENTRIES>{capped}</MAX_NROF_ENTRIES>"
            f"{status_xml}"
        )
        result = await _call_rfc(s4, "BAPI_PRODORD_GET_LIST", params_xml, user_id)
        if result.get("error"):
            return (
                f"BAPI_PRODORD_GET_LIST failed "
                f"(HTTP {result.get('status_code')}): {result.get('message','')}"
            )
        raw = result.get("raw", "")
        has_err, ret_msg = _soap_return(raw)
        if has_err:
            return f"BAPI_PRODORD_GET_LIST error:\n{ret_msg}"

        rows = _soap_items(raw, "ORDERLIST")
        if not rows:
            return f"No production orders found for plant {plant}{' / ' + material if material else ''}."

        header = (
            f"Production Orders — Plant {plant} (top {len(rows)}):\n\n"
            "| Order        | Material        | Status                   | PlannedQty | SchedEnd   |\n"
            "|--------------|-----------------|--------------------------|------------|------------|\n"
        )
        lines = []
        for r in rows:
            unit = r.get("UNIT_NET", "")
            planned = r.get("PLND_TOTAL_QTY", "0") or "0"
            status = r.get("SYS_STATUS", "") or "-"
            lines.append(
                f"| {r.get('ORDER_NUM',''):12} "
                f"| {r.get('MATERIAL',''):15} "
                f"| {status[:24]:24} "
                f"| {planned} {unit} "
                f"| {_fmt_date(r.get('BASIC_FIN',''))} |"
            )
        return header + "\n".join(lines)

    return StructuredTool(
        name="get_production_order",
        description=(
            "Retrieve SAP PP Production Order details via BAPI. "
            "Use production_order for a single order (returns full header + system status). "
            "Use plant to list orders — filter by material or status_filter "
            "(REL=Released, CNF=Confirmed, TECO=Technically Completed, DLV=Delivered). "
            "Returns: material, planned qty, confirmed qty, scheduled dates, system status."
        ),
        args_schema=GetProductionOrderInput,
        coroutine=get_production_order,
    )


def make_get_production_order_components(s4: "Client", user_id: str | None = None) -> StructuredTool:
    async def get_production_order_components(production_order: str) -> str:
        padded = _pad_order(production_order)
        params_xml = f"<NUMBER>{padded}</NUMBER>"
        result = await _call_rfc(s4, "BAPI_PRODORD_GET_DETAIL", params_xml, user_id)
        if result.get("error"):
            return (
                f"BAPI_PRODORD_GET_DETAIL failed "
                f"(HTTP {result.get('status_code')}): {result.get('message','')}"
            )
        raw = result.get("raw", "")
        has_err, ret_msg = _soap_return(raw)
        if has_err:
            return f"BAPI_PRODORD_GET_DETAIL error:\n{ret_msg}"

        rows = _soap_items(raw, "COMPONENT")
        if not rows:
            return f"No components found for production order {production_order}."

        lines = [f"Components for Production Order {production_order} ({len(rows)} items):\n"]
        short_ok = short_miss = 0
        for r in rows:
            try:
                req = float(r.get("REQD_QTY", 0) or 0)
                issued = float(r.get("ISSUED_QTY", 0) or 0)
            except (ValueError, TypeError):
                req = issued = 0.0
            unit = r.get("UNIT_NET", "") or r.get("BASE_UOM", "")
            open_qty = max(0.0, req - issued)
            backflush = " [BF]" if r.get("BACKFLUSH") in ("X", "x", "1") else ""
            mat_desc = r.get("SHORT_TEXT", "") or r.get("MAT_DESC", "") or r.get("DESCRIPT", "")
            reserv = r.get("RESERV_NO", "") or r.get("RESERVE", "")
            res_item = r.get("RES_ITEM", "") or r.get("RES_ITEM_NO", "")

            shortage = ""
            if open_qty > 0:
                short_ok += 1
                shortage = " ✓"

            lines.append(
                f"  Res {reserv}/{res_item:>4}  "
                f"Material: {r.get('MATERIAL',''):20}  "
                f"Req: {req:>8.3g} {unit}  "
                f"Issued: {issued:>8.3g}  "
                f"Open: {open_qty:>8.3g}{shortage}"
                f"{backflush}\n"
                f"    SLoc: {r.get('STGE_LOC','') or '-'}  "
                f"Desc: {mat_desc or '-'}"
            )
        lines.append(
            f"\nSummary: {short_ok} component(s) with open qty | "
            f"{len(rows) - short_ok} already fully issued"
        )
        return "\n".join(lines)

    return StructuredTool(
        name="get_production_order_components",
        description=(
            "List all BOM components (material reservations) for a production order via BAPI. "
            "Shows: material, required qty, issued (withdrawn) qty, open qty, storage location, "
            "backflush flag. Use to check what still needs to be issued before production."
        ),
        args_schema=GetProductionOrderComponentsInput,
        coroutine=get_production_order_components,
    )


def make_get_production_order_operations(s4: "Client", user_id: str | None = None) -> StructuredTool:
    async def get_production_order_operations(production_order: str) -> str:
        padded = _pad_order(production_order)
        params_xml = f"<NUMBER>{padded}</NUMBER>"
        result = await _call_rfc(s4, "BAPI_PRODORD_GET_DETAIL", params_xml, user_id)
        if result.get("error"):
            return (
                f"BAPI_PRODORD_GET_DETAIL failed "
                f"(HTTP {result.get('status_code')}): {result.get('message','')}"
            )
        raw = result.get("raw", "")
        has_err, ret_msg = _soap_return(raw)
        if has_err:
            return f"BAPI_PRODORD_GET_DETAIL error:\n{ret_msg}"

        rows = _soap_items(raw, "OPERATION")
        if not rows:
            return f"No operations found for production order {production_order}."

        header = (
            f"Operations for Production Order {production_order} ({len(rows)} ops):\n\n"
            "| Op   | Text                  | WorkCenter   | Status          | PlannedQty | ConfQty  |\n"
            "|------|-----------------------|--------------|-----------------|------------|----------|\n"
        )
        lines = []
        for r in rows:
            op_num = r.get("ACT_NUM", "") or r.get("ACTIVITY", "") or r.get("ACTVTY_NUM", "")
            desc = r.get("SHORT_TEXT", "") or r.get("DESCRIPTION", "") or r.get("WRKCTRCATG", "")
            wc = r.get("WORK_CNTR", "") or r.get("WORKCENTER", "")
            status = r.get("SYS_STATUS", "") or r.get("STATUS", "") or r.get("STATUS_LNG", "") or "-"
            unit = r.get("UNIT_QTY", "") or r.get("BASE_UOM", "")
            planned = r.get("BASE_QTY", "0") or "0"
            conf = r.get("CONF_YIELD", "0") or "0"
            lines.append(
                f"| {op_num:4} "
                f"| {desc[:21]:21} "
                f"| {wc:12} "
                f"| {status[:15]:15} "
                f"| {planned} {unit} "
                f"| {conf} {unit} |"
            )
        return header + "\n".join(lines)

    return StructuredTool(
        name="get_production_order_operations",
        description=(
            "List all routing operations for a production order via BAPI. "
            "Shows: operation number, description, work center, system status, "
            "planned qty, confirmed yield qty. "
            "Use before confirming to get the operation number (ACT_NUM) needed."
        ),
        args_schema=GetProductionOrderOperationsInput,
        coroutine=get_production_order_operations,
    )


def make_get_production_confirmations(s4: "Client", user_id: str | None = None) -> StructuredTool:
    async def get_production_confirmations(production_order: str, top: int = 50) -> str:
        capped = min(top, MAX_PAGE_SIZE)
        padded = _pad_order(production_order)
        params = _fmt_params({
            "$filter": f"ProductionOrder eq '{padded}'",
            "$select": (
                "ProductionOrderConfirmation,OperationConfirmationCount,"
                "ProductionOrder,ManufacturingOrderOperation,WorkCenter,"
                "ConfirmationYieldQuantity,ConfirmationScrapQuantity,"
                "ConfirmationReworkQuantity,ConfirmationUnit,"
                "IsFinalConfirmation,PostingDate,IsReversed,"
                "MfgOrderConfirmationEntryDate,EnteredByUser"
            ),
            "$orderby": "ProductionOrderConfirmation desc",
            "$top": str(capped),
        })
        result = await s4.get(
            f"{_CONF_SRV}/A_ProductionOrderConf",
            params=params,
            user_identity=user_id,
        )
        rows, err = _odata_results(result)
        if err:
            return err
        if not rows:
            return f"No confirmations found for production order {production_order}."

        header = (
            f"Confirmations for Production Order {production_order} ({len(rows)}):\n\n"
            "| ConfirmNo  | Op   | WorkCenter   | Yield    | Scrap | Final | Reversed | PostDate   |\n"
            "|------------|------|--------------|----------|-------|-------|----------|------------|\n"
        )
        lines = []
        for r in rows:
            is_final = "Yes" if r.get("IsFinalConfirmation") in (True, "true") else "No"
            reversed_ = "Yes" if r.get("IsReversed") in (True, "true") else "No"
            unit = r.get("ConfirmationUnit", "")
            lines.append(
                f"| {r.get('ProductionOrderConfirmation',''):10} "
                f"| {r.get('ManufacturingOrderOperation',''):4} "
                f"| {r.get('WorkCenter',''):12} "
                f"| {r.get('ConfirmationYieldQuantity','0')} {unit} "
                f"| {r.get('ConfirmationScrapQuantity','0')} "
                f"| {is_final:5} "
                f"| {reversed_:8} "
                f"| {r.get('PostingDate','-')} |"
            )
        return header + "\n".join(lines)

    return StructuredTool(
        name="get_production_confirmations",
        description=(
            "Retrieve all operation confirmations posted for a production order via OData. "
            "Shows: confirmation number, operation, work center, yield/scrap quantities, "
            "final confirmation flag, reversal status, and posting date. "
            "Use to check how much has already been confirmed and whether a final confirmation exists."
        ),
        args_schema=GetProductionConfirmationsInput,
        coroutine=get_production_confirmations,
    )
