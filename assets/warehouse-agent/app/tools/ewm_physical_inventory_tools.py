"""EWM Physical Inventory tools — OData V4.

Service: API_WHSE_PHYSINVTRYITEM_2
Base:    /sap/opu/odata4/sap/api_whse_physinvtryitem_2/srvd_a2x/sap/api_whse_physinvtryitem_2/0001
Entities: WhsePhysicalInventoryItem, WhsePhysicalInventoryCountItem, WhsePhysicalInventorySrlNmbr
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from s4hana_client import Client

logger = logging.getLogger(__name__)

_SRV = (
    "/sap/opu/odata4/sap/api_whse_physinvtryitem_2"
    "/srvd_a2x/sap/api_whse_physinvtryitem_2/0001"
)
MAX_PAGE_SIZE = 100

PINV_STATUS = {
    "ACTI": "Active",
    "COMP": "Completed",
    "CANC": "Cancelled",
    "CRTD": "Created",
    "PRTD": "Printed",
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


class GetPhysInventoryDocsInput(BaseModel):
    ewm_warehouse: str = Field(description="EWM Warehouse number — pass exactly as the user says (e.g. '1710', 'PBAR', 'BAR1')")
    doc_number: str = Field(default="", description="Physical inventory document number (optional)")
    doc_year: str = Field(default="", description="Physical inventory document year (optional, e.g. '2024')")
    storage_type: str = Field(default="", description="Storage type code (optional, e.g. 'Y042')")
    storage_bin: str = Field(default="", description="Storage bin (optional)")
    product: str = Field(default="", description="Product/material number (optional)")
    status: str = Field(default="", description="Status text: ACTI=Active, COMP=Completed, CANC=Cancelled, CRTD=Created (optional)")
    top: int = Field(default=50, description="Max records (max 100)")


class GetPhysInventoryCountItemsInput(BaseModel):
    ewm_warehouse: str = Field(description="EWM Warehouse number — pass exactly as the user says (e.g. '1710', 'PBAR', 'BAR1')")
    doc_number: str = Field(description="Physical inventory document number")
    doc_year: str = Field(default="", description="Physical inventory document year (optional)")


def make_get_phys_inventory_docs(s4: "Client", user_id: str | None = None) -> StructuredTool:
    async def get_phys_inventory_docs(
        ewm_warehouse: str,
        doc_number: str = "",
        doc_year: str = "",
        storage_type: str = "",
        storage_bin: str = "",
        product: str = "",
        status: str = "",
        top: int = 50,
    ) -> str:
        capped = min(top, MAX_PAGE_SIZE)
        filters = [f"EWMWarehouse eq '{ewm_warehouse}'"]
        if doc_number:
            filters.append(f"PhysicalInventoryDocNumber eq '{doc_number}'")
        if doc_year:
            filters.append(f"PhysicalInventoryDocYear eq '{doc_year}'")
        if storage_type:
            filters.append(f"EWMStorageType eq '{storage_type}'")
        if storage_bin:
            filters.append(f"EWMStorageBin eq '{storage_bin}'")
        if product:
            filters.append(f"Product eq '{product}'")
        if status:
            filters.append(f"PhysicalInventoryStatusText eq '{status}'")

        params: dict[str, Any] = {
            "$filter": " and ".join(filters),
            "$select": (
                "EWMWarehouse,PhysicalInventoryDocNumber,PhysicalInventoryDocYear,"
                "PhysicalInventoryItemNumber,PhysicalInventoryDocumentType,"
                "PhysicalInventoryStatusText,EWMStorageType,EWMStorageBin,"
                "Product,Batch,EWMStockType,WarehouseOrder,"
                "PInvBookQuantityIsFreeze,PhysicalInventoryIsBlock,PInvDocumentItemIsPrinted"
            ),
            "$top": str(capped),
        }
        result = await s4.get_v4(
            f"{_SRV}/WhsePhysicalInventoryItem", params=params, user_identity=user_id
        )
        rows = _results(result)
        if not rows:
            return f"No physical inventory documents found for warehouse {ewm_warehouse}."
        lines = [f"EWM Physical Inventory — WH {ewm_warehouse} (top {len(rows)}):"]
        for r in rows:
            st = r.get("PhysicalInventoryStatusText", "")
            frozen = " [FROZEN]" if r.get("PInvBookQuantityIsFreeze") else ""
            blocked = " [BLOCKED]" if r.get("PhysicalInventoryIsBlock") else ""
            lines.append(
                f"  Doc: {r.get('PhysicalInventoryDocNumber','')} / {r.get('PhysicalInventoryDocYear','')}  "
                f"Item: {r.get('PhysicalInventoryItemNumber','')}  "
                f"Type: {r.get('PhysicalInventoryDocumentType','') or '-'}  "
                f"Status: {PINV_STATUS.get(st, st) or '-'}{frozen}{blocked}  "
                f"Bin: {r.get('EWMStorageBin','') or '-'}  "
                f"StorType: {r.get('EWMStorageType','') or '-'}  "
                f"Product: {r.get('Product','') or '-'}  "
                f"WO: {r.get('WarehouseOrder','') or '-'}"
            )
        return "\n".join(lines)

    return StructuredTool(
        name="get_phys_inventory_docs",
        description=(
            "List EWM Physical Inventory document items for a warehouse. "
            "Filter by document number, year, storage type, bin, product, or status "
            "(ACTI=Active, COMP=Completed, CANC=Cancelled, CRTD=Created). "
            "Returns doc number, year, item, type, status, bin, storage type, product, warehouse order."
        ),
        args_schema=GetPhysInventoryDocsInput,
        coroutine=get_phys_inventory_docs,
    )


def make_get_phys_inventory_count_items(s4: "Client", user_id: str | None = None) -> StructuredTool:
    async def get_phys_inventory_count_items(
        ewm_warehouse: str,
        doc_number: str,
        doc_year: str = "",
    ) -> str:
        filters = [
            f"EWMWarehouse eq '{ewm_warehouse}'",
            f"PhysicalInventoryDocNumber eq '{doc_number}'",
        ]
        if doc_year:
            filters.append(f"PhysicalInventoryDocYear eq '{doc_year}'")

        params: dict[str, Any] = {
            "$filter": " and ".join(filters),
            "$select": (
                "EWMWarehouse,PhysicalInventoryDocNumber,PhysicalInventoryDocYear,"
                "PhysicalInventoryItemNumber,LineIndexOfPInvItem,"
                "EWMStorageBin,EWMStorageType,Product,Batch,EWMStockType,"
                "RequestedQuantity,RequestedQuantityUnit,"
                "PInvIsZeroCount,EWMStorageBinIsEmpty"
            ),
            "$top": str(MAX_PAGE_SIZE),
        }
        result = await s4.get_v4(
            f"{_SRV}/WhsePhysicalInventoryCountItem", params=params, user_identity=user_id
        )
        rows = _results(result)
        if not rows:
            return f"No count items found for physical inventory document {doc_number}."
        lines = [f"Count Items for Physical Inventory Doc {doc_number} / WH {ewm_warehouse}:"]
        for r in rows:
            zero = " [ZERO COUNT]" if r.get("PInvIsZeroCount") else ""
            empty = " [BIN EMPTY]" if r.get("EWMStorageBinIsEmpty") else ""
            lines.append(
                f"  Item: {r.get('PhysicalInventoryItemNumber','')} "
                f"Line: {r.get('LineIndexOfPInvItem','')}  "
                f"Bin: {r.get('EWMStorageBin','') or '-'}  "
                f"StorType: {r.get('EWMStorageType','') or '-'}  "
                f"Product: {r.get('Product','') or '-'}  "
                f"Batch: {r.get('Batch','') or '-'}  "
                f"StockType: {r.get('EWMStockType','') or '-'}  "
                f"ReqQty: {r.get('RequestedQuantity', 0)} {r.get('RequestedQuantityUnit','')}"
                f"{zero}{empty}"
            )
        return "\n".join(lines)

    return StructuredTool(
        name="get_phys_inventory_count_items",
        description=(
            "Retrieve count items for an EWM Physical Inventory document. "
            "Shows bin, storage type, product, batch, stock type, requested quantity, "
            "and flags for zero-count or empty bin."
        ),
        args_schema=GetPhysInventoryCountItemsInput,
        coroutine=get_phys_inventory_count_items,
    )
