"""Batch management tools: batch master search and batch classification.

Service root:
  BATCH_ROOT = /sap/opu/odata/sap/API_BATCH_SRV
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from s4hana_client import Client

import re

logger = logging.getLogger(__name__)

BATCH_ROOT = "/sap/opu/odata/sap/API_BATCH_SRV"
MAX_PAGE_SIZE = 100

_ODATA_DATE_RE = re.compile(r"/Date\((-?\d+)\)/")


def _fmt(params: dict[str, Any]) -> dict[str, Any]:
    params.setdefault("$format", "json")
    return params


def _date(val: Any) -> str:
    """Convert OData V2 /Date(ms)/ to YYYY-MM-DD, or return '-' for None/empty."""
    if not val:
        return "-"
    m = _ODATA_DATE_RE.search(str(val))
    if m:
        from datetime import datetime, timezone
        ms = int(m.group(1))
        return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
    return str(val)


def _results(payload: Any) -> list[dict]:
    if isinstance(payload, dict):
        if "error" in payload:
            return []
        inner = payload.get("d", payload)
        if isinstance(inner, dict):
            r = inner.get("results", [])
            return r if isinstance(r, list) else []
        if isinstance(inner, list):
            return inner
    if isinstance(payload, list):
        return payload
    return []


class SearchBatchesInput(BaseModel):
    material: str = Field(description="SAP material number")
    plant: str = Field(default="", description="Plant code (e.g. AM01) — blank for all plants")
    batch: str = Field(default="", description="Batch number — blank to search all batches")
    expiring_before: str = Field(
        default="",
        description=(
            "Return only batches whose shelf-life expiration date is before this date (YYYY-MM-DD). "
            "Useful for identifying near-expiry or already-expired batches."
        ),
    )
    include_deleted: bool = Field(default=False, description="Include batches marked for deletion")
    top: int = Field(default=50, description="Max rows to return (max 100)")


class GetBatchClassificationInput(BaseModel):
    material: str = Field(description="SAP material number")
    plant: str = Field(description="Plant code")
    batch: str = Field(description="Batch number")


def make_search_batches(s4: "Client", user_id: str | None = None) -> StructuredTool:
    async def search_batches(
        material: str,
        plant: str = "",
        batch: str = "",
        expiring_before: str = "",
        include_deleted: bool = False,
        top: int = 50,
    ) -> str:
        capped = min(top, MAX_PAGE_SIZE)
        filter_parts = [f"Material eq '{material}'"]
        if plant:
            filter_parts.append(f"Plant eq '{plant}'")
        if batch:
            filter_parts.append(f"Batch eq '{batch}'")
        if expiring_before:
            filter_parts.append(f"ShlfLfExpirtnDt lt datetime'{expiring_before}T00:00:00'")
        if not include_deleted:
            filter_parts.append("IsMarkedForDeletion eq false")

        params = _fmt({
            "$filter": " and ".join(filter_parts),
            "$select": (
                "Material,Plant,Batch,BatchBySupplier,"
                "MfgDate,ShlfLfExpirtnDt,BestByDate,"
                "CountryOfOrigin,BatchAvailabilityType,IsMarkedForDeletion,"
                "CreationDate,LastChangeDate"
            ),
            "$top": str(capped),
        })
        result = await s4.get(f"{BATCH_ROOT}/A_Batch", params=params, user_identity=user_id)
        rows = _results(result)
        if not rows:
            msg = f"No batches found for material {material}"
            if plant:
                msg += f" / plant {plant}"
            if batch:
                msg += f" / batch {batch}"
            return msg + "."

        lines = [f"Batches for {material}" + (f" / plant {plant}" if plant else " (all plants)") + ":"]
        for r in rows:
            exp = _date(r.get("ShlfLfExpirtnDt"))
            mfg = _date(r.get("MfgDate"))
            bbs = r.get("BatchBySupplier") or "-"
            avail = r.get("BatchAvailabilityType") or "-"
            coo = r.get("CountryOfOrigin") or "-"
            deleted = " [MARKED FOR DELETION]" if r.get("IsMarkedForDeletion") else ""
            lines.append(
                f"  Batch: {r.get('Batch', '')}  Plant: {r.get('Plant', '')}"
                f"  SupplierBatch: {bbs}  MfgDate: {mfg}  Expiry: {exp}"
                f"  AvailType: {avail}  CoO: {coo}{deleted}"
            )
        return "\n".join(lines)

    return StructuredTool(
        name="search_batches",
        description=(
            "Search batch master records for a material. Supports filtering by plant, "
            "batch number, and shelf-life expiration date (useful for near-expiry checks). "
            "Returns batch number, manufacturing date, expiry date, supplier batch, "
            "availability type, and country of origin."
        ),
        args_schema=SearchBatchesInput,
        coroutine=search_batches,
    )


def make_get_batch_classification(s4: "Client", user_id: str | None = None) -> StructuredTool:
    async def get_batch_classification(material: str, plant: str, batch: str) -> str:
        params = _fmt({
            "$filter": (
                f"Material eq '{material}' and Plant eq '{plant}' and Batch eq '{batch}'"
            ),
            "$select": (
                "Material,Plant,Batch,Characteristic,CharcValue,"
                "CharcValueUnit,CharcDecimalValue,CharcFromDecimalValue,CharcToDecimalValue"
            ),
            "$top": "200",
        })
        result = await s4.get(
            f"{BATCH_ROOT}/A_BatchClassification",
            params=params,
            user_identity=user_id,
        )
        rows = _results(result)
        if not rows:
            return (
                f"No classification characteristics found for "
                f"batch {batch} / material {material} / plant {plant}."
            )

        lines = [f"Batch classification — Batch: {batch}  Material: {material}  Plant: {plant}"]
        for r in rows:
            charc = r.get("Characteristic") or ""
            val = r.get("CharcValue") or ""
            dec = r.get("CharcDecimalValue") or ""
            uom = r.get("CharcValueUnit") or ""
            display_val = val if val else dec
            unit_str = f"  [{uom}]" if uom else ""
            lines.append(f"  {charc}: {display_val}{unit_str}")
        return "\n".join(lines)

    return StructuredTool(
        name="get_batch_classification",
        description=(
            "Retrieve batch classification characteristics and their values for a specific batch. "
            "Returns all characteristic names with assigned values (string or numeric) and units. "
            "Use this to read batch-specific quality or process attributes stored in the batch class."
        ),
        args_schema=GetBatchClassificationInput,
        coroutine=get_batch_classification,
    )
