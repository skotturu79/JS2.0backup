"""Inbound delivery tools.

Service root:
  INBDEL_ROOT = /sap/opu/odata/sap/API_INBOUND_DELIVERY_SRV;v=0002
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

INBDEL_ROOT = "/sap/opu/odata/sap/API_INBOUND_DELIVERY_SRV;v=0002"
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


# ---------------------------------------------------------------------------
# Input schemas
# ---------------------------------------------------------------------------

GR_STATUS_LABELS = {"A": "Not started", "B": "Partial", "C": "Complete"}


class GetInboundDeliveriesInput(BaseModel):
    plant: str = Field(default="", description="Receiving plant code (e.g. AM02) — leave blank for all")
    supplier: str = Field(default="", description="Supplier number (optional filter)")
    top: int = Field(default=20, description="Max deliveries to return (max 100)")


class GetInboundDeliveryDetailInput(BaseModel):
    delivery_document: str = Field(description="Inbound delivery document number")


class GetDeliveryItemsInput(BaseModel):
    delivery_document: str = Field(description="Inbound delivery document number")


class GetDeliveryDocFlowInput(BaseModel):
    delivery_document: str = Field(description="Inbound delivery document number")


# ---------------------------------------------------------------------------
# Tool factories
# ---------------------------------------------------------------------------

def make_get_inbound_deliveries(s4: "Client", user_id: str | None = None) -> StructuredTool:
    async def get_inbound_deliveries(
        plant: str = "", supplier: str = "", top: int = 20
    ) -> str:
        capped = min(top, MAX_PAGE_SIZE)

        if plant:
            # Plant lives on item level — query items filtered by plant, collect unique delivery numbers
            item_params = _fmt({
                "$filter": f"Plant eq '{plant}'",
                "$select": "DeliveryDocument,Material,Batch,Plant,ActualDeliveryQuantity,GoodsMovementStatus",
                "$orderby": "DeliveryDocument desc",
                "$top": str(capped),
            })
            item_result = await s4.get(
                f"{INBDEL_ROOT}/A_InbDeliveryItem",
                params=item_params,
                user_identity=user_id,
            )
            item_rows = _results(item_result)
            if not item_rows:
                return f"No inbound deliveries found for plant {plant}."
            # Unique delivery numbers preserving order
            seen: set = set()
            del_nums = []
            for r in item_rows:
                d = r.get("DeliveryDocument", "")
                if d and d not in seen:
                    seen.add(d)
                    del_nums.append(d)

            # Fetch headers for those deliveries
            lines = [f"Inbound Deliveries for Plant {plant} (top {len(del_nums)}):"]
            filter_expr = " or ".join(f"DeliveryDocument eq '{n}'" for n in del_nums[:10])
            hdr_params = _fmt({
                "$filter": filter_expr,
                "$select": "DeliveryDocument,DeliveryDocumentType,Supplier,ShippingPoint,DocumentDate,DeliveryDate,OverallGoodsMovementStatus",
            })
            hdr_result = await s4.get(
                f"{INBDEL_ROOT}/A_InbDeliveryHeader",
                params=hdr_params,
                user_identity=user_id,
            )
            hdr_map = {r.get("DeliveryDocument"): r for r in _results(hdr_result)}
            for n in del_nums:
                h = hdr_map.get(n, {})
                status = h.get("OverallGoodsMovementStatus", "")
                lines.append(
                    f"  Delivery: {n}  "
                    f"Type: {h.get('DeliveryDocumentType','')}  "
                    f"Supplier: {h.get('Supplier','') or '-'}  "
                    f"ShipPt: {h.get('ShippingPoint','')}  "
                    f"GR Status: {GR_STATUS_LABELS.get(status, status)}  "
                    f"Delivery Date: {h.get('DeliveryDate','')}"
                )
            return "\n".join(lines)
        else:
            # No plant filter — return headers directly
            params = _fmt({
                "$select": (
                    "DeliveryDocument,DeliveryDocumentType,Supplier,ShippingPoint,"
                    "DocumentDate,DeliveryDate,OverallGoodsMovementStatus"
                ),
                "$orderby": "DeliveryDocument desc",
                "$top": str(capped),
            })
            if supplier:
                params["$filter"] = f"Supplier eq '{supplier}'"
            result = await s4.get(
                f"{INBDEL_ROOT}/A_InbDeliveryHeader",
                params=params,
                user_identity=user_id,
            )
            rows = _results(result)
            if not rows:
                return "No inbound deliveries found."
            lines = [f"Inbound Deliveries (top {capped}):"]
            for r in rows:
                status = r.get("OverallGoodsMovementStatus", "")
                lines.append(
                    f"  Delivery: {r.get('DeliveryDocument','')}  "
                    f"Type: {r.get('DeliveryDocumentType','')}  "
                    f"Supplier: {r.get('Supplier','') or '-'}  "
                    f"ShipPt: {r.get('ShippingPoint','')}  "
                    f"GR Status: {GR_STATUS_LABELS.get(status, status)}  "
                    f"Delivery Date: {r.get('DeliveryDate','')}"
                )
            return "\n".join(lines)

    return StructuredTool(
        name="get_inbound_deliveries",
        description=(
            "List inbound delivery headers, optionally filtered by receiving plant and/or supplier. "
            "When plant is given, filters via delivery items (plant lives at item level). "
            "Returns delivery number, type, supplier, shipping point, GR status, and delivery date."
        ),
        args_schema=GetInboundDeliveriesInput,
        coroutine=get_inbound_deliveries,
    )


def make_get_inbound_delivery_detail(s4: "Client", user_id: str | None = None) -> StructuredTool:
    async def get_inbound_delivery_detail(delivery_document: str) -> str:
        result = await s4.get(
            f"{INBDEL_ROOT}/A_InbDeliveryHeader('{delivery_document}')",
            params=_fmt({}),
            user_identity=user_id,
        )
        if isinstance(result, dict) and result.get("error"):
            return f"Error fetching delivery {delivery_document}: {result.get('message', result)}"
        return json.dumps(result, indent=2)

    return StructuredTool(
        name="get_inbound_delivery_detail",
        description=(
            "Fetch full header details for a single inbound delivery document. "
            "Returns all header fields including status, dates, weights, and partner data."
        ),
        args_schema=GetInboundDeliveryDetailInput,
        coroutine=get_inbound_delivery_detail,
    )


def make_get_delivery_items(s4: "Client", user_id: str | None = None) -> StructuredTool:
    async def get_delivery_items(delivery_document: str) -> str:
        params = _fmt({
            "$filter": f"DeliveryDocument eq '{delivery_document}'",
            "$select": (
                "DeliveryDocument,DeliveryDocumentItem,Material,Plant,"
                "StorageLocation,Batch,ActualDeliveryQuantity,DeliveryQuantityUnit,"
                "GoodsReceiptStatus,OpenWarehouseTaskExists"
            ),
            "$top": str(MAX_PAGE_SIZE),
        })
        result = await s4.get(
            f"{INBDEL_ROOT}/A_InbDeliveryItem",
            params=params,
            user_identity=user_id,
        )
        rows = _results(result)
        if not rows:
            return f"No items found for inbound delivery {delivery_document}."
        lines = [f"Items for Inbound Delivery {delivery_document}:"]
        for r in rows:
            status = r.get("GoodsMovementStatus", "")
            status_label = GR_STATUS_LABELS.get(status, status)
            lines.append(
                f"  Item: {r.get('DeliveryDocumentItem','')}  "
                f"Material: {r.get('Material','')}  "
                f"Batch: {r.get('Batch','') or '-'}  "
                f"Plant: {r.get('Plant','')}  "
                f"SLoc: {r.get('StorageLocation','')}  "
                f"Qty: {r.get('ActualDeliveryQuantity','')} {r.get('DeliveryQuantityUnit','')}  "
                f"GR Status: {status_label}"
            )
        return "\n".join(lines)

    return StructuredTool(
        name="get_delivery_items",
        description=(
            "Retrieve all line items for an inbound delivery. "
            "Shows material, batch, plant, storage location, quantity, GR status, "
            "and whether open warehouse tasks exist."
        ),
        args_schema=GetDeliveryItemsInput,
        coroutine=get_delivery_items,
    )


def make_get_delivery_doc_flow(s4: "Client", user_id: str | None = None) -> StructuredTool:
    async def get_delivery_doc_flow(delivery_document: str) -> str:
        params = _fmt({
            "$filter": f"DeliveryDocument eq '{delivery_document}'",
            "$select": (
                "DeliveryDocument,PrecedingDocument,PrecedingDocumentCategory,"
                "SubsequentDocument,SubsequentDocumentCategory"
            ),
            "$top": str(MAX_PAGE_SIZE),
        })
        result = await s4.get(
            f"{INBDEL_ROOT}/A_InbDeliveryDocFlow",
            params=params,
            user_identity=user_id,
        )
        rows = _results(result)
        if not rows:
            return f"No document flow found for inbound delivery {delivery_document}."
        lines = [f"Document Flow for Inbound Delivery {delivery_document}:"]
        for r in rows:
            lines.append(
                f"  Preceding: {r.get('PrecedingDocument','')} "
                f"(Cat: {r.get('PrecedingDocumentCategory','')})  →  "
                f"Subsequent: {r.get('SubsequentDocument','')} "
                f"(Cat: {r.get('SubsequentDocumentCategory','')})"
            )
        return "\n".join(lines)

    return StructuredTool(
        name="get_delivery_doc_flow",
        description=(
            "Retrieve the document flow (preceding PO and subsequent GR material doc) "
            "for an inbound delivery. Useful for tracing from purchase order → delivery → GR."
        ),
        args_schema=GetDeliveryDocFlowInput,
        coroutine=get_delivery_doc_flow,
    )
