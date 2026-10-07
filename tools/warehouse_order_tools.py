"""Warehouse Order & Task tools — OData V4.

Service: API_WAREHOUSE_ORDER_TASK_2
Base:    /sap/opu/odata4/sap/api_warehouse_order_task_2/srvd_a2x/sap/api_warehouse_order_task_2/0001
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from s4hana_client import Client

logger = logging.getLogger(__name__)

_SRV = "/sap/opu/odata4/sap/api_warehouse_order_task_2/srvd_a2x/sap/api_warehouse_order_task_2/0001"
MAX_PAGE_SIZE = 100

ORDER_STATUS = {"": "Open", "A": "Canceled", "B": "Locked", "C": "Confirmed", "D": "In Process"}
TASK_STATUS = {"": "Open", "A": "Canceled", "C": "Confirmed"}


def _pad(value: str) -> str:
    """Zero-pad a numeric EWM document/task number to 10 digits only if shorter than 8 digits; leave longer numbers as-is."""
    return value.zfill(10) if value.isdigit() and len(value) < 8 else value


def _results(payload: Any) -> list[dict]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        if "error" in payload:
            return []
        r = payload.get("value", [])
        return r if isinstance(r, list) else []
    return []


class GetWarehouseOrdersInput(BaseModel):
    ewm_warehouse: str = Field(description="EWM Warehouse number — pass exactly as the user says (e.g. '1710', 'PBAR', 'BAR1')")
    status: str = Field(default="", description="Order status: A=Canceled, B=Locked, C=Confirmed, D=In Process — blank for all (Open orders have a blank status code)")
    activity_area: str = Field(default="", description="Activity area code (optional)")
    top: int = Field(default=50, description="Max records (max 100)")


class GetWarehouseTasksInput(BaseModel):
    ewm_warehouse: str = Field(description="EWM Warehouse number — pass exactly as the user says (e.g. '1710', 'PBAR', 'BAR1')")
    warehouse_order: str = Field(default="", description="Warehouse order number (optional)")
    warehouse_task: str = Field(default="", description="Specific warehouse task number (optional) — use to look up a single task and find its order number")
    product: str = Field(default="", description="Product/material number (optional)")
    executing_resource: str = Field(default="", description="Resource/forklift ID (optional)")
    queue: str = Field(default="", description="Queue name (optional, e.g. 'Q-910-020')")
    status: str = Field(default="", description="Task status: OPEN=Open (blank status), A=Canceled, C=Confirmed — leave blank to return all")
    top: int = Field(default=50, description="Max records (max 100)")


class GetWarehouseTaskDetailInput(BaseModel):
    ewm_warehouse: str = Field(description="EWM Warehouse number — pass exactly as the user says (e.g. '1710', 'PBAR', 'BAR1')")
    warehouse_order: str = Field(description="Warehouse order number")
    warehouse_task: str = Field(description="Warehouse task number")
    warehouse_task_item: str = Field(default="0", description="Warehouse task item (default 0)")


def make_get_warehouse_orders(s4: "Client", user_id: str | None = None) -> StructuredTool:
    async def get_warehouse_orders(
        ewm_warehouse: str,
        status: str = "",
        activity_area: str = "",
        top: int = 50,
    ) -> str:
        capped = min(top, MAX_PAGE_SIZE)
        filters = [f"EWMWarehouse eq '{ewm_warehouse}'"]
        if status == "OPEN":
            filters.append("WarehouseOrderStatus eq ''")
        elif status:
            filters.append(f"WarehouseOrderStatus eq '{status}'")
        if activity_area:
            filters.append(f"ActivityArea eq '{activity_area}'")

        params: dict[str, Any] = {
            "$filter": " and ".join(filters),
            "$select": (
                "EWMWarehouse,WarehouseOrder,WarehouseOrderStatus,"
                "ActivityArea,Queue,ExecutingResource,"
                "WhseOrderCreationDateTime,WarehouseOrderStartDateTime,"
                "WhseProcessTypeDocumentHdr,CreatedByUser"
            ),
            "$orderby": "WhseOrderCreationDateTime desc",
            "$top": str(capped),
        }
        result = await s4.get_v4(f"{_SRV}/WarehouseOrder", params=params, user_identity=user_id)
        rows = _results(result)
        if not rows:
            return f"No warehouse orders found for warehouse {ewm_warehouse}."
        lines = [f"Warehouse Orders — WH {ewm_warehouse} (top {len(rows)}):"]
        for r in rows:
            st = r.get("WarehouseOrderStatus", "")
            lines.append(
                f"  Order: {r.get('WarehouseOrder','')}  "
                f"Status: {ORDER_STATUS.get(st, st)}  "
                f"Area: {r.get('ActivityArea','') or '-'}  "
                f"Queue: {r.get('Queue','') or '-'}  "
                f"Resource: {r.get('ExecutingResource','') or '-'}  "
                f"ProcType: {r.get('WhseProcessTypeDocumentHdr','') or '-'}  "
                f"Created: {r.get('WhseOrderCreationDateTime','') or '-'}"
            )
        return "\n".join(lines)

    return StructuredTool(
        name="get_warehouse_orders",
        description=(
            "List EWM Warehouse Orders for a given warehouse. "
            "Filter by status: A=Canceled, B=Locked, C=Confirmed, D=In Process, OPEN=Open (blank status). "
            "Leave status blank to return all orders. "
            "Does NOT support queue filtering — use get_warehouse_tasks for queue-based lookups. "
            "Returns order number, status, activity area, queue, executing resource, process type."
        ),
        args_schema=GetWarehouseOrdersInput,
        coroutine=get_warehouse_orders,
    )


def make_get_warehouse_tasks(s4: "Client", user_id: str | None = None) -> StructuredTool:
    async def get_warehouse_tasks(
        ewm_warehouse: str,
        warehouse_order: str = "",
        warehouse_task: str = "",
        product: str = "",
        executing_resource: str = "",
        queue: str = "",
        status: str = "",
        top: int = 50,
    ) -> str:
        capped = min(top, MAX_PAGE_SIZE)
        filters = [f"EWMWarehouse eq '{ewm_warehouse}'"]
        if warehouse_order:
            filters.append(f"WarehouseOrder eq '{_pad(warehouse_order)}'")
        if warehouse_task:
            filters.append(f"WarehouseTask eq '{_pad(warehouse_task)}'")
        if product:
            filters.append(f"Product eq '{product}'")
        if executing_resource:
            filters.append(f"ExecutingResource eq '{executing_resource}'")
        if queue:
            filters.append(f"WarehouseOrderQueue eq '{queue}'")
        if status == "OPEN":
            filters.append("WarehouseTaskStatus eq ''")
        elif status:
            filters.append(f"WarehouseTaskStatus eq '{status}'")

        params: dict[str, Any] = {
            "$filter": " and ".join(filters),
            "$select": (
                "EWMWarehouse,WarehouseOrder,WarehouseTask,WarehouseTaskItem,"
                "WarehouseTaskStatus,WarehouseProcessType,Product,"
                "WarehouseOrderQueue,SourceStorageBin,DestinationStorageBin,"
                "TargetQuantityInBaseUnit,ActualQuantityInBaseUnit,BaseUnit,"
                "TargetQuantityInAltvUnit,ActualQuantityInAltvUnit,AlternativeUnit,"
                "ExecutingResource,WhseTaskCrtnUTCDateTime"
            ),
            "$orderby": "WhseTaskCrtnUTCDateTime desc",
            "$top": str(capped),
        }
        result = await s4.get_v4(f"{_SRV}/WarehouseTask", params=params, user_identity=user_id)
        rows = _results(result)
        if not rows:
            label = f"warehouse {ewm_warehouse}"
            if warehouse_order:
                label += f" / order {warehouse_order}"
            return f"No warehouse tasks found for {label}."

        header = (
            f"Warehouse Tasks — WH {ewm_warehouse} (top {len(rows)}):\n\n"
            "| Task       | Order    | Status | Product | Queue        | From    | To              | TgtQty          | ActQty | Resource |\n"
            "|------------|----------|--------|---------|--------------|---------|-----------------|-----------------|--------|----------|\n"
        )
        lines = []
        for r in rows:
            st = r.get("WarehouseTaskStatus", "")
            tgt_base = r.get("TargetQuantityInBaseUnit", "") or "0"
            base_unit = r.get("BaseUnit", "")
            tgt_alt = r.get("TargetQuantityInAltvUnit", "")
            alt_unit = r.get("AlternativeUnit", "")
            if tgt_alt and alt_unit and alt_unit != base_unit:
                qty_str = f"{tgt_alt} {alt_unit} ({tgt_base} {base_unit})"
            else:
                qty_str = f"{tgt_base} {base_unit}"
            lines.append(
                f"| {r.get('WarehouseTask','')} "
                f"| {r.get('WarehouseOrder','')} "
                f"| {TASK_STATUS.get(st, st) or 'Open'} "
                f"| {r.get('Product','') or '-'} "
                f"| {r.get('WarehouseOrderQueue','') or '-'} "
                f"| {r.get('SourceStorageBin','') or '-'} "
                f"| {r.get('DestinationStorageBin','') or '-'} "
                f"| {qty_str} "
                f"| {r.get('ActualQuantityInBaseUnit','') or '0'} "
                f"| {r.get('ExecutingResource','') or '-'} |"
            )
        return header + "\n".join(lines)

    return StructuredTool(
        name="get_warehouse_tasks",
        description=(
            "List EWM Warehouse Tasks for a warehouse. "
            "Filter by warehouse_task (single task lookup — also reveals its order number), "
            "warehouse_order, product, executing_resource, queue (e.g. 'Q-910-020'), or status "
            "(OPEN=Open, A=Canceled, C=Confirmed — blank for all). "
            "Open tasks have blank status in SAP — use status='OPEN' to get only open tasks. "
            "Use warehouse_task filter to find the warehouse_order when only the task number is known. "
            "Returns task number, order, status, product, queue, source/dest bin, quantities, resource."
        ),
        args_schema=GetWarehouseTasksInput,
        coroutine=get_warehouse_tasks,
    )


def make_get_warehouse_task_detail(s4: "Client", user_id: str | None = None) -> StructuredTool:
    async def get_warehouse_task_detail(
        ewm_warehouse: str,
        warehouse_order: str,
        warehouse_task: str,
        warehouse_task_item: str = "0",
    ) -> str:
        path = (
            f"{_SRV}/WarehouseTask("
            f"EWMWarehouse='{ewm_warehouse}',"
            f"WarehouseTask='{_pad(warehouse_task)}',"
            f"WarehouseTaskItem={warehouse_task_item})"
        )
        result = await s4.get_v4(path, user_identity=user_id)
        if isinstance(result, dict) and result.get("error"):
            return f"Error: {result.get('message', result)}"
        if not result:
            return f"Task {warehouse_task} not found in order {warehouse_order}."
        if isinstance(result, dict):
            st = result.get("WarehouseTaskStatus", "")
            tgt_base = result.get('TargetQuantityInBaseUnit','') or '0'
            base_unit = result.get('BaseUnit','')
            tgt_alt = result.get('TargetQuantityInAltvUnit','')
            alt_unit = result.get('AlternativeUnit','')
            if tgt_alt and alt_unit and alt_unit != base_unit:
                tgt_display = f"{tgt_alt} {alt_unit} ({tgt_base} {base_unit})"
                confirm_hint = f"  Confirm Hint  : use actual_quantity={tgt_alt}, unit_of_measure={alt_unit}"
            else:
                tgt_display = f"{tgt_base} {base_unit}"
                confirm_hint = f"  Confirm Hint  : use actual_quantity={tgt_base}, unit_of_measure={base_unit}"
            return (
                f"Warehouse Task Detail:\n"
                f"  Warehouse     : {result.get('EWMWarehouse','')}\n"
                f"  Order         : {result.get('WarehouseOrder','')}\n"
                f"  Task          : {result.get('WarehouseTask','')} / Item {result.get('WarehouseTaskItem','')}\n"
                f"  Status        : {TASK_STATUS.get(st, st)}\n"
                f"  Process Type  : {result.get('WarehouseProcessType','') or '-'}\n"
                f"  Product       : {result.get('Product','') or '-'}\n"
                f"  Batch         : {result.get('Batch','') or '-'}\n"
                f"  Source Bin    : {result.get('SourceStorageBin','') or '-'}\n"
                f"  Dest Bin      : {result.get('DestinationStorageBin','') or '-'}\n"
                f"  Target Qty    : {tgt_display}\n"
                f"  Actual Qty    : {result.get('ActualQuantityInBaseUnit','') or '0'} {base_unit}\n"
                f"  Resource      : {result.get('ExecutingResource','') or '-'}\n"
                f"  Created       : {result.get('WhseTaskCrtnUTCDateTime','') or '-'}\n"
                f"{confirm_hint}"
            )
        return str(result)

    return StructuredTool(
        name="get_warehouse_task_detail",
        description=(
            "Fetch full detail for a single EWM Warehouse Task. "
            "Returns all fields: status, product, batch, source/destination bin, "
            "target and actual quantities, executing resource."
        ),
        args_schema=GetWarehouseTaskDetailInput,
        coroutine=get_warehouse_task_detail,
    )
