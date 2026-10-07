"""EWM Warehouse Master tools — OData V4.

Services:
  API_WAREHOUSE_2  — Warehouse master data and Storage Type definitions

Base: /sap/opu/odata4/sap/api_warehouse_2/srvd_a2x/sap/api_warehouse_2/0001
Entities: Warehouse, WarehouseStorageType
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from s4hana_client import Client

logger = logging.getLogger(__name__)

_SRV = "/sap/opu/odata4/sap/api_warehouse_2/srvd_a2x/sap/api_warehouse_2/0001"
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


# ── Warehouse list ────────────────────────────────────────────────────────────

class GetWarehousesInput(BaseModel):
    ewm_warehouse: str = Field(
        default="",
        description="Filter by specific EWM warehouse number, e.g. '1710'. Leave blank to list all warehouses."
    )


def make_get_warehouses(s4: "Client", user_id: str | None = None) -> StructuredTool:
    async def _run(ewm_warehouse: str = "") -> str:
        params: dict[str, Any] = {"$top": MAX_PAGE_SIZE, "$format": "json"}
        filters = []
        if ewm_warehouse:
            filters.append(f"EWMWarehouse eq '{ewm_warehouse}'")
        if filters:
            params["$filter"] = " and ".join(filters)

        result = await s4.get_v4(f"{_SRV}/Warehouse", params=params, user_identity=user_id)
        rows = _items(result)
        if isinstance(result, dict) and result.get("error"):
            return f"Error fetching warehouses: {result.get('message','unknown error')}"
        if not rows:
            return "No warehouses found."

        lines = [f"EWM Warehouses ({len(rows)} found):", ""]
        for w in rows:
            lines.append(f"  Warehouse: {w.get('EWMWarehouse','?')}")
        return "\n".join(lines)

    return StructuredTool.from_function(
        coroutine=_run,
        name="get_warehouses",
        description=(
            "List EWM warehouses on the active system. Optionally filter by warehouse number. "
            "Use this to discover available warehouse numbers."
        ),
        args_schema=GetWarehousesInput,
    )


# ── Storage Types ─────────────────────────────────────────────────────────────

class GetStorageTypesInput(BaseModel):
    ewm_warehouse: str = Field(
        description="EWM Warehouse number — pass exactly as the user says (e.g. '1710', 'PBAR', 'BAR1')"
    )
    ewm_storage_type: str = Field(
        default="",
        description="Filter by specific storage type code (e.g. 'BLDR', 'Y042'). Leave blank for all."
    )


def make_get_storage_types(s4: "Client", user_id: str | None = None) -> StructuredTool:
    async def _run(ewm_warehouse: str, ewm_storage_type: str = "") -> str:
        filters = [f"EWMWarehouse eq '{ewm_warehouse}'"]
        if ewm_storage_type:
            filters.append(f"EWMStorageType eq '{ewm_storage_type}'")

        params: dict[str, Any] = {
            "$top": MAX_PAGE_SIZE,
            "$filter": " and ".join(filters),
            "$format": "json",
        }

        result = await s4.get_v4(f"{_SRV}/WarehouseStorageType", params=params, user_identity=user_id)
        rows = _items(result)
        if isinstance(result, dict) and result.get("error"):
            return f"Error fetching storage types: {result.get('message','unknown error')}"
        if not rows:
            return f"No storage types found for warehouse {ewm_warehouse}."

        lines = [
            f"Storage Types — Warehouse {ewm_warehouse} ({len(rows)} found):",
            f"{'Storage Type':<16}",
            "-" * 16,
        ]
        for r in rows:
            lines.append(f"{r.get('EWMStorageType','?'):<16}")
        return "\n".join(lines)

    return StructuredTool.from_function(
        coroutine=_run,
        name="get_storage_types",
        description=(
            "List all EWM storage types defined for a warehouse. "
            "Use this to discover valid storage type codes (e.g. BLDR, Y042, Y910) "
            "before querying bins or stock by storage type."
        ),
        args_schema=GetStorageTypesInput,
    )
