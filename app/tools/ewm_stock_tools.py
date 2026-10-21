"""EWM Stock tools — OData V4.

Services:
  API_WHSE_AVAILABLESTOCK  — Available stock per warehouse/product/bin
  API_WHSE_PHYSSTOCKPROD   — Physical stock totals per product

Base paths (V4):
  /sap/opu/odata4/sap/api_whse_availablestock/srvd_a2x/sap/api_whse_availablestock/0001
  /sap/opu/odata4/sap/api_whse_physstockprod/srvd_a2x/sap/api_whse_physstockprod/0001
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from s4hana_client import Client

logger = logging.getLogger(__name__)

_AVAIL_SRV = "/sap/opu/odata4/sap/api_whse_availablestock/srvd_a2x/sap/api_whse_availablestock/0001"
_PHYS_SRV = "/sap/opu/odata4/sap/api_whse_physstockprod/srvd_a2x/sap/api_whse_physstockprod/0001"
MAX_PAGE_SIZE = 100

STOCK_TYPE_LABELS = {
    "F1": "Unrestricted",
    "F2": "Unrestricted",
    "S1": "Blocked",
    "S2": "Blocked",
    "Q1": "Quality Inspection",
    "Q2": "Quality Inspection",
    "R1": "Returns",
    "T1": "In Transfer",
    "W1": "Work in Process",
}


def _results(payload: Any) -> list[dict]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        if "error" in payload:
            return []
        r = payload.get("value", [])
        return r if isinstance(r, list) else []
    return []


class GetEWMAvailableStockInput(BaseModel):
    ewm_warehouse: str = Field(description="EWM Warehouse number — pass exactly as the user says (e.g. '1710', 'PBAR', 'BAR1')")
    product: str = Field(default="", description="Product/material number (optional)")
    storage_bin: str = Field(default="", description="Storage bin (optional)")
    storage_type: str = Field(default="", description="Storage type code (optional, e.g. 'BLDR', 'Y910')")
    stock_type: str = Field(default="", description="Stock type: F1/F2=Unrestricted, Q1/Q2=Quality Inspection, S1/S2=Blocked, T1=In Transfer")
    top: int = Field(default=50, description="Max records (max 100)")


class GetEWMPhysicalStockInput(BaseModel):
    ewm_warehouse: str = Field(description="EWM Warehouse number — pass exactly as the user says (e.g. '1710', 'PBAR', 'BAR1')")
    product: str = Field(default="", description="Product/material number (optional)")
    top: int = Field(default=50, description="Max records (max 100)")


def make_get_ewm_available_stock(s4: "Client", user_id: str | None = None) -> StructuredTool:
    async def get_ewm_available_stock(
        ewm_warehouse: str,
        product: str = "",
        storage_bin: str = "",
        storage_type: str = "",
        stock_type: str = "",
        top: int = 50,
    ) -> str:
        capped = min(top, MAX_PAGE_SIZE)
        filters = [f"EWMWarehouse eq '{ewm_warehouse}'"]
        if product:
            filters.append(f"Product eq '{product}'")
        if storage_bin:
            filters.append(f"EWMStorageBin eq '{storage_bin}'")
        if storage_type:
            filters.append(f"EWMStorageType eq '{storage_type}'")
        if stock_type:
            st = stock_type.upper().strip()
            if len(st) == 1:
                filters.append(f"startswith(EWMStockType,'{st}') eq true")
            else:
                filters.append(f"EWMStockType eq '{st}'")

        params: dict[str, Any] = {
            "$filter": " and ".join(filters),
            "$select": (
                "EWMWarehouse,Product,Batch,EWMStorageBin,EWMStorageType,EWMStockType,"
                "AvailableEWMStockQty,EWMStockQuantityBaseUnit,EWMStockOwner"
            ),
            "$top": str(capped),
        }
        result = await s4.get_v4(f"{_AVAIL_SRV}/WarehouseAvailableStock", params=params, user_identity=user_id)
        rows = _results(result)
        if not rows:
            label = f"warehouse {ewm_warehouse}"
            if product:
                label += f" / product {product}"
            return f"No EWM available stock found for {label}."
        lines = [f"EWM Available Stock — WH {ewm_warehouse}" + (f" / {product}" if product else "") + f" (top {len(rows)}):"]
        for r in rows:
            st = r.get("EWMStockType", "")
            lines.append(
                f"  Product: {r.get('Product','')}  "
                f"Batch: {r.get('Batch','') or '-'}  "
                f"Bin: {r.get('EWMStorageBin','') or '-'}  "
                f"StorType: {r.get('EWMStorageType','') or '-'}  "
                f"StockType: {STOCK_TYPE_LABELS.get(st, st)}  "
                f"Qty: {r.get('AvailableEWMStockQty','') or '0'} {r.get('EWMStockQuantityBaseUnit','')}  "
                f"Owner: {r.get('EWMStockOwner','') or '-'}"
            )
        return "\n".join(lines)

    return StructuredTool(
        name="get_ewm_available_stock",
        description=(
            "Retrieve EWM bin-level available stock in a warehouse. "
            "Filter by product, storage bin, storage type (e.g. 'BLDR', 'Y910'), and/or stock type "
            "(F1/F2=Unrestricted, Q1/Q2=Quality Inspection, S1/S2=Blocked, T1=In Transfer). "
            "Returns product, batch, bin, storage type, stock type, and quantity."
        ),
        args_schema=GetEWMAvailableStockInput,
        coroutine=get_ewm_available_stock,
    )


def make_get_ewm_physical_stock(s4: "Client", user_id: str | None = None) -> StructuredTool:
    async def get_ewm_physical_stock(
        ewm_warehouse: str,
        product: str = "",
        top: int = 50,
    ) -> str:
        capped = min(top, MAX_PAGE_SIZE)
        filters = [f"EWMWarehouse eq '{ewm_warehouse}'"]
        if product:
            filters.append(f"Product eq '{product}'")

        params: dict[str, Any] = {
            "$filter": " and ".join(filters),
            "$select": (
                "EWMWarehouse,Product,Batch,EWMStockType,EWMStorageBin,EWMStorageType,"
                "EWMStockQuantityInBaseUnit,EWMStockQuantityBaseUnit"
            ),
            "$top": str(capped),
        }
        result = await s4.get_v4(f"{_PHYS_SRV}/WarehousePhysicalStockProducts", params=params, user_identity=user_id)
        rows = _results(result)
        if not rows:
            label = f"warehouse {ewm_warehouse}"
            if product:
                label += f" / product {product}"
            return f"No EWM physical stock found for {label}."
        lines = [f"EWM Physical Stock — WH {ewm_warehouse}" + (f" / {product}" if product else "") + f" (top {len(rows)}):"]
        for r in rows:
            st = r.get("EWMStockType", "")
            lines.append(
                f"  Product: {r.get('Product','')}  "
                f"Batch: {r.get('Batch','') or '-'}  "
                f"Bin: {r.get('EWMStorageBin','') or '-'}  "
                f"StorType: {r.get('EWMStorageType','') or '-'}  "
                f"StockType: {STOCK_TYPE_LABELS.get(st, st)}  "
                f"PhysQty: {r.get('EWMStockQuantityInBaseUnit','') or '0'} {r.get('EWMStockQuantityBaseUnit','')}"
            )
        return "\n".join(lines)

    return StructuredTool(
        name="get_ewm_physical_stock",
        description=(
            "Retrieve EWM physical stock totals per product and stock type in a warehouse. "
            "Returns product, batch, stock type, and physical quantity. "
            "Use for inventory totals; use get_ewm_available_stock for bin-level detail."
        ),
        args_schema=GetEWMPhysicalStockInput,
        coroutine=get_ewm_physical_stock,
    )
