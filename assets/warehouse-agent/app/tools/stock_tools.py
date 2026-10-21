"""Stock tools: material stock levels and stock overview.

Service roots:
  STOCK_ROOT = /sap/opu/odata/sap/API_MATERIAL_STOCK_SRV
"""
from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from s4hana_client import Client

logger = logging.getLogger(__name__)

STOCK_ROOT = "/sap/opu/odata/sap/API_MATERIAL_STOCK_SRV"
MAX_PAGE_SIZE = 100


def _fmt(params: dict[str, Any]) -> dict[str, Any]:
    params.setdefault("$format", "json")
    return params


def _results(payload: Any) -> list[dict]:
    if isinstance(payload, dict):
        if "error" in payload:
            return []
        inner = payload.get("results", payload)
        if isinstance(inner, list):
            return inner
        if isinstance(inner, dict):
            r = inner.get("results", [])
            return r if isinstance(r, list) else []
    if isinstance(payload, list):
        return payload
    return []


STOCK_TYPE_LABELS = {
    "01": "Unrestricted",
    "02": "Quality Inspection",
    "03": "Blocked",
    "06": "In Transit",
    "07": "Restricted Use",
}


class GetMaterialStockInput(BaseModel):
    material: str = Field(description="SAP material number")
    plant: str = Field(default="", description="SAP plant code (e.g. AM01) — leave blank for all plants")
    storage_location: str = Field(default="", description="Storage location (optional)")
    top: int = Field(default=100, description="Max rows to return (max 100)")


class GetStockOverviewInput(BaseModel):
    material: str = Field(description="SAP material number")
    plant: str = Field(default="", description="SAP plant code — leave blank for all plants")


def make_get_material_stock(s4: "Client", user_id: str | None = None) -> StructuredTool:
    async def get_material_stock(
        material: str, plant: str = "", storage_location: str = "", top: int = 100
    ) -> str:
        capped = min(top, MAX_PAGE_SIZE)
        # A_MatlStkInAcctMod has Plant/StorageLocation/Batch as key fields
        filter_parts = [f"Material eq '{material}'"]
        if plant:
            filter_parts.append(f"Plant eq '{plant}'")
        if storage_location:
            filter_parts.append(f"StorageLocation eq '{storage_location}'")
        params = _fmt({
            "$filter": " and ".join(filter_parts),
            "$select": (
                "Material,Plant,StorageLocation,Batch,MaterialBaseUnit,"
                "MatlWrhsStkQtyInMatlBaseUnit,InventoryStockType"
            ),
            "$top": str(capped),
        })
        result = await s4.get(
            f"{STOCK_ROOT}/A_MatlStkInAcctMod",
            params=params,
            user_identity=user_id,
        )
        rows = _results(result)
        if not rows:
            return f"No stock found for material {material}" + (f" at plant {plant}." if plant else ".")
        lines = [f"Stock for {material}" + (f" / Plant {plant}" if plant else " (all plants)") + ":"]
        for r in rows:
            sloc = r.get("StorageLocation", "") or "-"
            batch = r.get("Batch", "") or "-"
            qty = r.get("MatlWrhsStkQtyInMatlBaseUnit", "")
            uom = r.get("MaterialBaseUnit", "")
            stype = r.get("InventoryStockType", "")
            stype_label = STOCK_TYPE_LABELS.get(stype, stype)
            lines.append(
                f"  Plant: {r.get('Plant','')}  SLoc: {sloc}  Batch: {batch}"
                f"  Qty: {qty} {uom}  StockType: {stype_label}"
            )
        return "\n".join(lines)

    return StructuredTool(
        name="get_material_stock",
        description=(
            "Retrieve current warehouse stock for a material, optionally filtered by plant "
            "and/or storage location. Returns quantities per batch, storage location, and stock type "
            "(Unrestricted, Quality Inspection, Blocked, In Transit)."
        ),
        args_schema=GetMaterialStockInput,
        coroutine=get_material_stock,
    )


def make_get_stock_overview(s4: "Client", user_id: str | None = None) -> StructuredTool:
    async def get_stock_overview(material: str, plant: str = "") -> str:
        filter_parts = [f"Material eq '{material}'"]
        if plant:
            filter_parts.append(f"Plant eq '{plant}'")
        params = _fmt({
            "$filter": " and ".join(filter_parts),
            "$select": (
                "Material,Plant,StorageLocation,Batch,MaterialBaseUnit,"
                "MatlWrhsStkQtyInMatlBaseUnit,InventoryStockType"
            ),
            "$top": str(MAX_PAGE_SIZE),
        })
        result = await s4.get(
            f"{STOCK_ROOT}/A_MatlStkInAcctMod",
            params=params,
            user_identity=user_id,
        )
        rows = _results(result)
        if not rows:
            return f"No stock found for material {material}" + (f" at plant {plant}." if plant else ".")
        # Group by plant + stock type for a summary view
        lines = [f"Stock Overview — {material}" + (f" / Plant {plant}" if plant else " (all plants)") + ":"]
        for r in rows:
            qty = r.get("MatlWrhsStkQtyInMatlBaseUnit", "0")
            if qty == "0" or qty == "0.000":
                continue
            stype = r.get("InventoryStockType", "")
            stype_label = STOCK_TYPE_LABELS.get(stype, stype)
            lines.append(
                f"  Plant: {r.get('Plant','')}  SLoc: {r.get('StorageLocation','') or '-'}"
                f"  Batch: {r.get('Batch','') or '-'}"
                f"  Qty: {qty} {r.get('MaterialBaseUnit','')}  [{stype_label}]"
            )
        if len(lines) == 1:
            return f"All stock is zero for material {material}."
        return "\n".join(lines)

    return StructuredTool(
        name="get_stock_overview",
        description=(
            "Retrieve stock overview for a material showing only non-zero quantities, "
            "grouped by plant, storage location, batch, and stock type "
            "(Unrestricted, Quality Inspection, Blocked, In Transit)."
        ),
        args_schema=GetStockOverviewInput,
        coroutine=get_stock_overview,
    )
