"""Production Order OData V2 read tools — uses API_PRODUCTION_ORDER_2_SRV.

Entity sets:
  A_ProductionOrder_2          — order header (key: ManufacturingOrder)
  A_ProductionOrderStatus_2    — system/user status per order
  A_ProductionOrderComponent_2 — BOM components (material reservations)
  A_ProductionOrderOperation_2 — routing operations

Service path:
  /sap/opu/odata/sap/API_PRODUCTION_ORDER_2_SRV
"""
from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from s4hana_client import Client

logger = logging.getLogger(__name__)

_SRV = "/sap/opu/odata/sap/API_PRODUCTION_ORDER_2_SRV"
MAX_PAGE_SIZE = 100

_EPOCH_RE = re.compile(r"/Date\((-?\d+)\)/")


def _fmt_odate(v: str) -> str:
    """Convert OData V2 /Date(epoch_ms)/ → YYYY-MM-DD, or return '-'."""
    if not v:
        return "-"
    m = _EPOCH_RE.search(str(v))
    if m:
        ms = int(m.group(1))
        if ms <= 0:
            return "-"
        from datetime import datetime, timezone
        return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
    return str(v)


def _results(payload: Any) -> tuple[list[dict], str]:
    """Unwrap OData V2 JSON response. Returns (rows, error_message)."""
    if isinstance(payload, dict):
        err = payload.get("error")
        if err:
            if isinstance(err, dict):
                msg = err.get("message", {})
                text = msg.get("value", str(err)) if isinstance(msg, dict) else str(msg)
                return [], f"SAP error [{err.get('code','')}]: {text}"
            return [], f"SAP error: {err}"
        # V2: {"d": {"results": [...]}} — client returns the d-level dict
        inner = payload.get("results", payload)
        if isinstance(inner, list):
            return inner, ""
        if isinstance(inner, dict):
            r = inner.get("results", [])
            return (r if isinstance(r, list) else []), ""
    if isinstance(payload, list):
        return payload, ""
    return [], ""


def _flag(v: Any) -> str:
    return "Yes" if v in ("X", "x", True, "true") else "No"


# ---------------------------------------------------------------------------
# Input schemas
# ---------------------------------------------------------------------------

class GetProductionOrdersODataInput(BaseModel):
    production_order: str = Field(default="", description="Exact production order number for single lookup")
    plant: str = Field(default="", description="Plant code to list orders (e.g. 'BAR1', '1710')")
    material: str = Field(default="", description="Material number filter (optional)")
    order_type: str = Field(default="", description="Order type filter (e.g. 'PP01', 'YBM1') — optional")
    status_filter: str = Field(
        default="",
        description="Filter by status: REL=Released, CNF=Confirmed, TECO=TechComplete, OPEN=not closed",
    )
    top: int = Field(default=20, description="Max records (max 100)")


class GetProductionOrderStatusInput(BaseModel):
    production_order: str = Field(description="Production order number")


class GetProductionOrderComponentsODataInput(BaseModel):
    production_order: str = Field(description="Production order number")


class GetProductionOrderOperationsODataInput(BaseModel):
    production_order: str = Field(description="Production order number")


# ---------------------------------------------------------------------------
# Tool factories
# ---------------------------------------------------------------------------

def make_get_production_orders_odata(s4: "Client", user_id: str | None = None) -> StructuredTool:
    async def get_production_orders_odata(
        production_order: str = "",
        plant: str = "",
        material: str = "",
        order_type: str = "",
        status_filter: str = "",
        top: int = 20,
    ) -> str:
        capped = min(top, MAX_PAGE_SIZE)
        filters = []

        if production_order:
            padded = production_order.zfill(12) if production_order.isdigit() else production_order
            filters.append(f"ManufacturingOrder eq '{padded}'")
        if plant:
            filters.append(f"Plant eq '{plant}'")
        if material:
            filters.append(f"Material eq '{material}'")
        if order_type:
            filters.append(f"ManufacturingOrderType eq '{order_type}'")
        if status_filter == "REL":
            filters.append("OrderIsReleased eq 'X'")
        elif status_filter == "CNF":
            filters.append("OrderIsConfirmed eq 'X'")
        elif status_filter == "TECO":
            filters.append("OrderIsTechnicallyCompleted eq 'X'")
        elif status_filter == "OPEN":
            filters.append("OrderIsTechnicallyCompleted eq ''")
            filters.append("OrderIsClosed eq ''")

        params = {
            "$format": "json",
            "$top": str(capped),
            "$select": (
                "ManufacturingOrder,ManufacturingOrderType,Material,Plant,"
                "ProductionVersion,TotalQuantity,MfgOrderConfirmedYieldQty,"
                "ProductionUnit,MfgOrderPlannedStartDate,MfgOrderPlannedEndDate,"
                "MfgOrderActualReleaseDate,OrderIsReleased,OrderIsConfirmed,"
                "OrderIsTechnicallyCompleted,OrderIsClosed,ProductionSupervisor,MRPController"
            ),
            "$orderby": "ManufacturingOrder desc",
        }
        if filters:
            params["$filter"] = " and ".join(filters)

        result = await s4.get(
            f"{_SRV}/A_ProductionOrder_2",
            params=params,
            user_identity=user_id,
        )
        rows, err = _results(result)
        if err:
            return err
        if not rows:
            desc = production_order or f"plant {plant}" + (f" / {material}" if material else "")
            return f"No production orders found for {desc}."

        if production_order and len(rows) == 1:
            r = rows[0]
            unit = r.get("ProductionUnit", "")
            lines = [
                f"Production Order: {r.get('ManufacturingOrder','')}",
                f"  Type        : {r.get('ManufacturingOrderType','')}",
                f"  Material    : {r.get('Material','')}",
                f"  Plant       : {r.get('Plant','')}  Version: {r.get('ProductionVersion','')}",
                f"  Planned Qty : {r.get('TotalQuantity','')} {unit}",
                f"  Confirmed   : {r.get('MfgOrderConfirmedYieldQty','')} {unit}",
                f"  Sched Start : {_fmt_odate(r.get('MfgOrderPlannedStartDate',''))}",
                f"  Sched End   : {_fmt_odate(r.get('MfgOrderPlannedEndDate',''))}",
                f"  Released    : {_flag(r.get('OrderIsReleased',''))}",
                f"  Confirmed   : {_flag(r.get('OrderIsConfirmed',''))}",
                f"  TechComplete: {_flag(r.get('OrderIsTechnicallyCompleted',''))}",
                f"  Closed      : {_flag(r.get('OrderIsClosed',''))}",
                f"  Supervisor  : {r.get('ProductionSupervisor','-') or '-'}",
                f"  MRP Ctrl    : {r.get('MRPController','-') or '-'}",
            ]
            return "\n".join(lines)

        header = (
            f"Production Orders ({len(rows)} found):\n\n"
            "| Order        | Type  | Material             | Qty          | PlannedStart | Rel | CNF | TECO |\n"
            "|--------------|-------|----------------------|--------------|--------------|-----|-----|------|\n"
        )
        lines = []
        for r in rows:
            unit = r.get("ProductionUnit", "")
            qty = f"{r.get('TotalQuantity','')} {unit}"
            lines.append(
                f"| {r.get('ManufacturingOrder',''):12} "
                f"| {r.get('ManufacturingOrderType',''):5} "
                f"| {r.get('Material',''):20} "
                f"| {qty:12} "
                f"| {_fmt_odate(r.get('MfgOrderPlannedStartDate',''))} "
                f"| {'X' if r.get('OrderIsReleased')=='X' else ' ':3} "
                f"| {'X' if r.get('OrderIsConfirmed')=='X' else ' ':3} "
                f"| {'X' if r.get('OrderIsTechnicallyCompleted')=='X' else ' ':4} |"
            )
        return header + "\n".join(lines)

    return StructuredTool(
        name="get_production_orders_v2",
        description=(
            "Search SAP production orders via OData V2 (API_PRODUCTION_ORDER_2_SRV). "
            "Use production_order for single order detail. Use plant to list orders — "
            "filter by material, order_type, or status_filter "
            "(REL=Released, CNF=Confirmed, TECO=TechComplete, OPEN=not closed/TECO). "
            "Returns: material, qty, planned dates, release/confirmation/completion flags."
        ),
        args_schema=GetProductionOrdersODataInput,
        coroutine=get_production_orders_odata,
    )


def make_get_production_order_status_odata(s4: "Client", user_id: str | None = None) -> StructuredTool:
    async def get_production_order_status_odata(production_order: str) -> str:
        padded = production_order.zfill(12) if production_order.isdigit() else production_order
        params = {
            "$format": "json",
            "$filter": f"ManufacturingOrder eq '{padded}'",
            "$select": "ManufacturingOrder,StatusCode,IsUserStatus,StatusShortName,StatusName",
        }
        result = await s4.get(
            f"{_SRV}/A_ProductionOrderStatus_2",
            params=params,
            user_identity=user_id,
        )
        rows, err = _results(result)
        if err:
            return err
        if not rows:
            return f"No status entries found for production order {production_order}."

        sys_statuses = [r for r in rows if not r.get("IsUserStatus")]
        usr_statuses = [r for r in rows if r.get("IsUserStatus")]

        lines = [f"Status for Production Order {production_order}:\n"]
        if sys_statuses:
            lines.append("  System Status:")
            for r in sys_statuses:
                lines.append(f"    {r.get('StatusShortName',''):8}  {r.get('StatusCode','')}  {r.get('StatusName','')}")
        if usr_statuses:
            lines.append("  User Status:")
            for r in usr_statuses:
                lines.append(f"    {r.get('StatusShortName',''):8}  {r.get('StatusCode','')}  {r.get('StatusName','')}")
        return "\n".join(lines)

    return StructuredTool(
        name="get_production_order_status_v2",
        description=(
            "Fetch all system and user status codes for a production order via OData V2. "
            "Returns: status code (e.g. I0001), short name (CRTD/REL/PCNF/CNF/DLV/TECO/CLSD), "
            "and full status name. Shows both system statuses and user-defined statuses."
        ),
        args_schema=GetProductionOrderStatusInput,
        coroutine=get_production_order_status_odata,
    )


def make_get_production_order_components_odata(s4: "Client", user_id: str | None = None) -> StructuredTool:
    async def get_production_order_components_odata(production_order: str) -> str:
        padded = production_order.zfill(12) if production_order.isdigit() else production_order
        params = {
            "$format": "json",
            "$filter": f"ManufacturingOrder eq '{padded}'",
            "$select": (
                "ManufacturingOrder,Reservation,ReservationItem,Material,Plant,"
                "StorageLocation,SupplyArea,RequiredQuantity,WithdrawnQuantity,"
                "ConfirmedAvailableQuantity,BaseUnit,MatlCompIsMarkedForBackflush,"
                "ReservationIsFinallyIssued,MatlCompRequirementDate,BOMItemDescription"
            ),
        }
        result = await s4.get(
            f"{_SRV}/A_ProductionOrderComponent_2",
            params=params,
            user_identity=user_id,
        )
        rows, err = _results(result)
        if err:
            return err
        if not rows:
            return f"No components found for production order {production_order}."

        lines = [f"Components for Production Order {production_order} ({len(rows)} items):\n"]
        short_cnt = fully_issued = 0
        for r in rows:
            try:
                req = float(r.get("RequiredQuantity") or 0)
                withdrawn = float(r.get("WithdrawnQuantity") or 0)
                confirmed_avail = float(r.get("ConfirmedAvailableQuantity") or 0)
            except (ValueError, TypeError):
                req = withdrawn = confirmed_avail = 0.0

            unit = r.get("BaseUnit", "")
            open_qty = max(0.0, req - withdrawn)
            backflush = " [BF]" if r.get("MatlCompIsMarkedForBackflush") in ("X", "x") else ""
            final_issue = " [FINAL]" if r.get("ReservationIsFinallyIssued") in ("X", "x") else ""
            desc = r.get("BOMItemDescription", "") or ""
            req_date = _fmt_odate(r.get("MatlCompRequirementDate", ""))

            if open_qty > 0:
                short_cnt += 1
            else:
                fully_issued += 1

            shortage_flag = "" if open_qty > 0 else " ✓"
            lines.append(
                f"  Res {r.get('Reservation',''):10}/{r.get('ReservationItem',''):4}  "
                f"Material: {r.get('Material',''):20}  "
                f"Req: {req:>8.3g} {unit}  "
                f"Withdrawn: {withdrawn:>8.3g}  "
                f"Open: {open_qty:>8.3g}{shortage_flag}"
                f"{backflush}{final_issue}\n"
                f"    SLoc: {r.get('StorageLocation','-') or '-'}  "
                f"SupplyArea: {r.get('SupplyArea','-') or '-'}  "
                f"ReqDate: {req_date}  "
                f"ConfAvail: {confirmed_avail:.3g}  "
                f"Desc: {desc or '-'}"
            )

        lines.append(
            f"\nSummary: {short_cnt} component(s) with open qty | "
            f"{fully_issued} already fully issued"
        )
        return "\n".join(lines)

    return StructuredTool(
        name="get_production_order_components_v2",
        description=(
            "List all BOM components (material reservations) for a production order via OData V2. "
            "Shows: material, required qty, withdrawn qty, open qty, storage location, supply area, "
            "confirmed available qty, backflush flag. Use to check material availability and shortages."
        ),
        args_schema=GetProductionOrderComponentsODataInput,
        coroutine=get_production_order_components_odata,
    )


def make_get_production_order_operations_odata(s4: "Client", user_id: str | None = None) -> StructuredTool:
    async def get_production_order_operations_odata(production_order: str) -> str:
        padded = production_order.zfill(12) if production_order.isdigit() else production_order
        params = {
            "$format": "json",
            "$filter": f"ManufacturingOrder eq '{padded}'",
            "$select": (
                "ManufacturingOrder,ManufacturingOrderOperation,ManufacturingOrderSequence,"
                "MfgOrderOperationText,WorkCenter,ProductionPlant,"
                "OperationIsReleased,OperationIsConfirmed,OperationIsTechlyCompleted,"
                "OpPlannedTotalQuantity,OpTotalConfirmedYieldQty,OperationUnit,"
                "OpErlstSchedldExecStrtDte,OpErlstSchedldExecEndDte,"
                "OpActualExecutionStartDate,OpActualExecutionEndDate"
            ),
            "$orderby": "ManufacturingOrderSequence,ManufacturingOrderOperation",
        }
        result = await s4.get(
            f"{_SRV}/A_ProductionOrderOperation_2",
            params=params,
            user_identity=user_id,
        )
        rows, err = _results(result)
        if err:
            return err
        if not rows:
            return f"No operations found for production order {production_order}."

        header = (
            f"Operations for Production Order {production_order} ({len(rows)} ops):\n\n"
            "| Seq | Op   | Description           | WorkCenter   | Rel | CNF | TECO | PlannedQty   | ConfQty      |\n"
            "|-----|------|-----------------------|--------------|-----|-----|------|--------------|---------------|\n"
        )
        lines = []
        for r in rows:
            unit = r.get("OperationUnit", "")
            lines.append(
                f"| {r.get('ManufacturingOrderSequence',''):3} "
                f"| {r.get('ManufacturingOrderOperation',''):4} "
                f"| {(r.get('MfgOrderOperationText','') or '')[:21]:21} "
                f"| {r.get('WorkCenter',''):12} "
                f"| {'X' if r.get('OperationIsReleased')=='X' else ' ':3} "
                f"| {'X' if r.get('OperationIsConfirmed')=='X' else ' ':3} "
                f"| {'X' if r.get('OperationIsTechlyCompleted')=='X' else ' ':4} "
                f"| {r.get('OpPlannedTotalQuantity','0')} {unit} "
                f"| {r.get('OpTotalConfirmedYieldQty','0')} {unit} |"
            )
        return header + "\n".join(lines)

    return StructuredTool(
        name="get_production_order_operations_v2",
        description=(
            "List all routing operations for a production order via OData V2. "
            "Shows: sequence, operation number, description, work center, "
            "release/confirmation/completion flags, planned vs confirmed yield qty. "
            "Use to check operation status and get operation numbers for confirmations."
        ),
        args_schema=GetProductionOrderOperationsODataInput,
        coroutine=get_production_order_operations_odata,
    )
