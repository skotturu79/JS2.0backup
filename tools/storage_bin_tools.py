"""Storage Bin tools — OData V4.

Services:
  API_WHSE_STORAGE_BIN_2      — Storage Bin master data
  API_WHSE_FIXBIN_ASSGNMNT    — Fixed bin assignments per product
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from s4hana_client import Client

logger = logging.getLogger(__name__)

_BIN_SRV = "/sap/opu/odata4/sap/api_whse_storage_bin_2/srvd_a2x/sap/api_warehouse_storage_bin_2/0001"
_FIXBIN_SRV = "/sap/opu/odata4/sap/api_whse_fixbin_assgnmnt/srvd_a2x/sap/api_whse_fixbin_assgnmnt/0001"
MAX_PAGE_SIZE = 100


def _results(payload: Any) -> list[dict]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        if "error" in payload:
            return []
        r = payload.get("value", [])
        return r if isinstance(r, list) else []
    return []


class GetStorageBinsInput(BaseModel):
    ewm_warehouse: str = Field(description="EWM Warehouse number — pass exactly as the user says (e.g. '1710', 'PBAR', 'BAR1')")
    storage_bin: str = Field(default="", description="Specific storage bin to look up (optional)")
    storage_type: str = Field(default="", description="Storage type code (optional, e.g. 'BLDR', 'Y042')")
    storage_section: str = Field(default="", description="Storage section code (optional)")
    bin_type: str = Field(default="", description="Bin type (optional)")
    empty_only: bool = Field(default=False, description="If true, return only empty bins")
    top: int = Field(default=50, description="Max records (max 100)")


class GetFixedBinAssignmentsInput(BaseModel):
    ewm_warehouse: str = Field(description="EWM Warehouse number — pass exactly as the user says (e.g. '1710', 'PBAR', 'BAR1')")
    product: str = Field(default="", description="Product/material number (optional)")
    storage_bin: str = Field(default="", description="Storage bin (optional)")
    top: int = Field(default=50, description="Max records (max 100)")


def make_get_storage_bins(s4: "Client", user_id: str | None = None) -> StructuredTool:
    async def get_storage_bins(
        ewm_warehouse: str,
        storage_bin: str = "",
        storage_type: str = "",
        storage_section: str = "",
        bin_type: str = "",
        empty_only: bool = False,
        top: int = 50,
    ) -> str:
        capped = min(top, MAX_PAGE_SIZE)
        filters = [f"EWMWarehouse eq '{ewm_warehouse}'"]
        if storage_bin:
            filters.append(f"EWMStorageBin eq '{storage_bin}'")
        if storage_type:
            filters.append(f"EWMStorageType eq '{storage_type}'")
        if storage_section:
            filters.append(f"EWMStorageSection eq '{storage_section}'")
        if bin_type:
            filters.append(f"EWMStorageBinType eq '{bin_type}'")
        if empty_only:
            filters.append("EWMStorageBinIsEmpty eq true")

        params: dict[str, Any] = {
            "$filter": " and ".join(filters),
            "$select": (
                "EWMWarehouse,EWMStorageBin,EWMStorageType,EWMStorageSection,"
                "EWMStorageBinType,EWMStorageBinIsEmpty,EWMStorageBinIsFull,"
                "EWMStorBinIsBlockedForPutaway,EWMStorBinIsBlockedForRemoval,"
                "EWMStorageBinMaximumWeight,WeightUnit"
            ),
            "$top": str(capped),
        }
        result = await s4.get_v4(f"{_BIN_SRV}/WarehouseStorageBin", params=params, user_identity=user_id)
        rows = _results(result)
        if not rows:
            return f"No storage bins found for warehouse {ewm_warehouse}."
        lines = [f"Storage Bins — WH {ewm_warehouse} (top {len(rows)}):"]
        for r in rows:
            blocked = []
            if r.get("EWMStorBinIsBlockedForPutaway"):
                blocked.append("Putaway")
            if r.get("EWMStorBinIsBlockedForRemoval"):
                blocked.append("Removal")
            empty = "Empty" if r.get("EWMStorageBinIsEmpty") else ("Full" if r.get("EWMStorageBinIsFull") else "In Use")
            lines.append(
                f"  Bin: {r.get('EWMStorageBin','')}  "
                f"Type: {r.get('EWMStorageType','') or '-'}  "
                f"Section: {r.get('EWMStorageSection','') or '-'}  "
                f"BinType: {r.get('EWMStorageBinType','') or '-'}  "
                f"State: {empty}  "
                f"MaxWt: {r.get('EWMStorageBinMaximumWeight','') or '-'} {r.get('WeightUnit','') or ''}  "
                f"Blocked: {', '.join(blocked) if blocked else '-'}"
            )
        return "\n".join(lines)

    return StructuredTool(
        name="get_storage_bins",
        description=(
            "Retrieve storage bin master data for a warehouse. "
            "Look up a specific bin by storage_bin, or filter by storage type, section, and/or bin type. "
            "Use empty_only=true to find available empty bins. "
            "Returns bin number, storage type, section, bin type, empty/full state, max weight, and block status."
        ),
        args_schema=GetStorageBinsInput,
        coroutine=get_storage_bins,
    )


def make_get_fixed_bin_assignments(s4: "Client", user_id: str | None = None) -> StructuredTool:
    async def get_fixed_bin_assignments(
        ewm_warehouse: str,
        product: str = "",
        storage_bin: str = "",
        top: int = 50,
    ) -> str:
        capped = min(top, MAX_PAGE_SIZE)
        filters = [f"EWMWarehouse eq '{ewm_warehouse}'"]
        if product:
            filters.append(f"Product eq '{product}'")
        if storage_bin:
            filters.append(f"EWMStorageBin eq '{storage_bin}'")

        params: dict[str, Any] = {
            "$filter": " and ".join(filters),
            "$select": (
                "EWMWarehouse,EWMStorageBin,EWMStorageType,Product,"
                "EWMMaximumStorageQuantity,EWMMaximumStorageQuantityUnit,"
                "EWMMinimumStorageQuantity,EWMMinimumStorageQuantityUnit"
            ),
            "$top": str(capped),
        }
        result = await s4.get_v4(
            f"{_FIXBIN_SRV}/WarehouseFixedBinAssignment", params=params, user_identity=user_id
        )
        rows = _results(result)
        if not rows:
            label = f"warehouse {ewm_warehouse}"
            if product:
                label += f" / product {product}"
            return f"No fixed bin assignments found for {label}."
        lines = [f"Fixed Bin Assignments — WH {ewm_warehouse}" + (f" / {product}" if product else "") + f" (top {len(rows)}):"]
        for r in rows:
            lines.append(
                f"  Bin: {r.get('EWMStorageBin','')}  "
                f"Type: {r.get('EWMStorageType','') or '-'}  "
                f"Product: {r.get('Product','')}  "
                f"MaxQty: {r.get('EWMMaximumStorageQuantity','') or '-'} {r.get('EWMMaximumStorageQuantityUnit','') or ''}  "
                f"MinQty: {r.get('EWMMinimumStorageQuantity','') or '-'} {r.get('EWMMinimumStorageQuantityUnit','') or ''}"
            )
        return "\n".join(lines)

    return StructuredTool(
        name="get_fixed_bin_assignments",
        description=(
            "Retrieve fixed bin assignments (product-to-bin assignments) for a warehouse. "
            "Shows which bin a product is permanently assigned to, with min/max/replenishment quantities. "
            "Useful for put-away guidance and replenishment planning."
        ),
        args_schema=GetFixedBinAssignmentsInput,
        coroutine=get_fixed_bin_assignments,
    )
