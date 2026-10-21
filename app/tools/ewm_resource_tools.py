"""EWM Warehouse Resource tools — OData V4.

Service: API_WAREHOUSE_RESOURCE_2
Base:    /sap/opu/odata4/sap/api_warehouse_resource_2/srvd_a2x/sap/api_warehouse_resource_2/0001
Entities: WarehouseResource, WhseResourceGroupQueueSqnc

WarehouseResource = a user/worker logged onto a warehouse resource (forklift/RF device).
Fields: EWMWarehouse, EWMResource, UserName, EWMResourceGroup, EWMResourceType,
        WarehouseOrderQueue, EWMCurrentQueue, EWMStorTypeOfLastWhseTaskConf,
        EWMResourceLogonDateTime, EWMRsceIsLoggedOntoByCurUser
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from s4hana_client import Client

logger = logging.getLogger(__name__)

_SRV = "/sap/opu/odata4/sap/api_warehouse_resource_2/srvd_a2x/sap/api_warehouse_resource_2/0001"
MAX_PAGE_SIZE = 100


def _items(payload: Any) -> list[dict]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        if "error" in payload:
            return []
        v = payload.get("value", [])
        return v if isinstance(v, list) else []
    return []


# ── Warehouse Resources ───────────────────────────────────────────────────────

class GetWarehouseResourcesInput(BaseModel):
    ewm_warehouse: str = Field(
        description="EWM Warehouse number — pass exactly as the user says (e.g. '1710', 'PBAR', 'BAR1')"
    )
    ewm_resource: str = Field(
        default="",
        description="Filter by specific resource ID (user name / device ID). Leave blank for all."
    )
    ewm_resource_group: str = Field(
        default="",
        description="Filter by resource group code (e.g. 'YALL', 'RGRP'). Leave blank for all."
    )
    ewm_resource_type: str = Field(
        default="",
        description="Filter by resource type code. Leave blank for all."
    )
    logged_on_only: bool = Field(
        default=False,
        description="If true, return only resources currently logged on."
    )


def make_get_warehouse_resources(s4: "Client", user_id: str | None = None) -> StructuredTool:
    async def _run(
        ewm_warehouse: str,
        ewm_resource: str = "",
        ewm_resource_group: str = "",
        ewm_resource_type: str = "",
        logged_on_only: bool = False,
    ) -> str:
        filters = [f"EWMWarehouse eq '{ewm_warehouse}'"]
        if ewm_resource:
            filters.append(f"EWMResource eq '{ewm_resource}'")
        if ewm_resource_group:
            filters.append(f"EWMResourceGroup eq '{ewm_resource_group}'")
        if ewm_resource_type:
            filters.append(f"EWMResourceType eq '{ewm_resource_type}'")

        params: dict[str, Any] = {
            "$top": MAX_PAGE_SIZE,
            "$filter": " and ".join(filters),
            "$select": (
                "EWMWarehouse,EWMResource,UserName,EWMResourceGroup,EWMResourceType,"
                "WarehouseOrderQueue,EWMCurrentQueue,EWMStorTypeOfLastWhseTaskConf,"
                "EWMResourceLogonDateTime,EWMRsceIsLoggedOntoByCurUser"
            ),
            "$format": "json",
        }

        result = await s4.get_v4(f"{_SRV}/WarehouseResource", params=params, user_identity=user_id)
        rows = _items(result)
        if isinstance(result, dict) and result.get("error"):
            return f"Error fetching warehouse resources: {result.get('message','unknown error')}"

        if logged_on_only:
            rows = [r for r in rows if r.get("EWMRsceIsLoggedOntoByCurUser")]

        if not rows:
            return f"No warehouse resources found for warehouse {ewm_warehouse}."

        lines = [
            f"Warehouse Resources — WH {ewm_warehouse} ({len(rows)} found):",
            "",
            f"{'Resource':<14} {'User':<14} {'Group':<8} {'Type':<8} {'Queue':<20} {'Last ST':<10} {'LoggedOn':<8} {'Last Logon'}",
            "-" * 110,
        ]
        for r in rows:
            logon_dt = r.get("EWMResourceLogonDateTime", "") or ""
            if logon_dt and "T" in logon_dt:
                logon_dt = logon_dt[:10]
            lines.append(
                f"{r.get('EWMResource',''):<14} "
                f"{r.get('UserName',''):<14} "
                f"{r.get('EWMResourceGroup',''):<8} "
                f"{r.get('EWMResourceType',''):<8} "
                f"{r.get('EWMCurrentQueue') or r.get('WarehouseOrderQueue',''):<20} "
                f"{r.get('EWMStorTypeOfLastWhseTaskConf',''):<10} "
                f"{'Yes' if r.get('EWMRsceIsLoggedOntoByCurUser') else 'No':<8} "
                f"{logon_dt}"
            )
        return "\n".join(lines)

    return StructuredTool.from_function(
        coroutine=_run,
        name="get_warehouse_resources",
        description=(
            "List EWM warehouse resources (operators/workers logged onto devices). "
            "Shows resource ID, user name, resource group, resource type, current queue assignment, "
            "last confirmed storage type, and logon status. "
            "Filter by resource group or type to see teams. Use logged_on_only=true to see who is active."
        ),
        args_schema=GetWarehouseResourcesInput,
    )


# ── Resource Group Queue Sequence ────────────────────────────────────────────

class GetResourceGroupQueuesInput(BaseModel):
    ewm_warehouse: str = Field(
        description="EWM Warehouse number — pass exactly as the user says (e.g. '1710', 'PBAR', 'BAR1')"
    )
    ewm_resource_group: str = Field(
        default="",
        description="Filter by resource group (e.g. 'RGRP'). Leave blank for all groups."
    )


def make_get_resource_group_queues(s4: "Client", user_id: str | None = None) -> StructuredTool:
    async def _run(ewm_warehouse: str, ewm_resource_group: str = "") -> str:
        filters = [f"EWMWarehouse eq '{ewm_warehouse}'"]
        if ewm_resource_group:
            filters.append(f"EWMResourceGroup eq '{ewm_resource_group}'")

        params: dict[str, Any] = {
            "$top": MAX_PAGE_SIZE,
            "$filter": " and ".join(filters),
            "$orderby": "EWMResourceGroup,EWMResourceGroupQueueSqncNmbr",
            "$format": "json",
        }

        result = await s4.get_v4(
            f"{_SRV}/WhseResourceGroupQueueSqnc", params=params, user_identity=user_id
        )
        rows = _items(result)
        if isinstance(result, dict) and result.get("error"):
            return f"Error: {result.get('message','unknown error')}"
        if not rows:
            return f"No resource group queue sequences found for warehouse {ewm_warehouse}."

        lines = [
            f"Resource Group Queue Sequences — WH {ewm_warehouse} ({len(rows)} found):",
            "",
            f"{'Resource Group':<18} {'Seq #':<8} {'Queue'}",
            "-" * 60,
        ]
        for r in rows:
            lines.append(
                f"{r.get('EWMResourceGroup','(default)'):<18} "
                f"{r.get('EWMResourceGroupQueueSqncNmbr',''):<8} "
                f"{r.get('WarehouseOrderQueue','')}"
            )
        return "\n".join(lines)

    return StructuredTool.from_function(
        coroutine=_run,
        name="get_resource_group_queues",
        description=(
            "Show the queue sequence assigned to each EWM resource group in a warehouse. "
            "Reveals which warehouse order queues (INBOUND, OUTBOUND, REPL, etc.) are worked by each group "
            "and in what priority order. Useful for understanding workflow routing."
        ),
        args_schema=GetResourceGroupQueuesInput,
    )
