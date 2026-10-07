"""EWM Outbound Delivery tools — OData V4.

Service: API_WHSE_OUTB_DELIVERY_ORDER_2
Base:    /sap/opu/odata4/sap/api_warehouse_odo_2/srvd_a2x/sap/api_whse_outb_delivery_order_2/0001
Entity sets: WhseOutboundDeliveryOrderHead, WhseOutboundDeliveryOrderItem
Note: EWMOutbDlvOrdAdhocLoadgIsActv column missing in DB — always use $select to avoid 500.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from s4hana_client import Client

logger = logging.getLogger(__name__)

_SRV = "/sap/opu/odata4/sap/api_warehouse_odo_2/srvd_a2x/sap/api_whse_outb_delivery_order_2/0001"
MAX_PAGE_SIZE = 100

# Safe header fields — EWMOutbDlvOrdAdhocLoadgIsActv excluded (missing DB column)
_HDR_SELECT = (
    "EWMWarehouse,EWMOutboundDeliveryOrder,EWMDeliveryDocumentType,"
    "ShipToParty,ShipToPartyName,Carrier,EWMRoute,"
    "PlannedDeliveryUTCDateTime,EWMShippingReadinessStatus,"
    "EWMOutbDlvOrdImmdLoadgIsActv"
)

ODO_STATUS = {
    "1": "Not Started",
    "2": "In Process",
    "3": "Completed",
    "A": "Not Started",
    "B": "In Process",
    "C": "Completed",
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


class GetEWMOutboundDeliveriesInput(BaseModel):
    ewm_warehouse: str = Field(description="EWM Warehouse number — pass exactly as the user says (e.g. '1710', 'PBAR', 'BAR1')")
    ship_to_party: str = Field(default="", description="Ship-to party (customer number, optional)")
    top: int = Field(default=50, description="Max records (max 100)")


class GetEWMOutboundDeliveryItemsInput(BaseModel):
    ewm_warehouse: str = Field(description="EWM Warehouse number — pass exactly as the user says (e.g. '1710', 'PBAR', 'BAR1')")
    outbound_delivery_order: str = Field(description="Outbound delivery order number")


def make_get_ewm_outbound_deliveries(s4: "Client", user_id: str | None = None) -> StructuredTool:
    async def get_ewm_outbound_deliveries(
        ewm_warehouse: str,
        ship_to_party: str = "",
        top: int = 50,
    ) -> str:
        capped = min(top, MAX_PAGE_SIZE)
        filters = [f"EWMWarehouse eq '{ewm_warehouse}'"]
        if ship_to_party:
            filters.append(f"ShipToParty eq '{ship_to_party}'")

        params: dict[str, Any] = {
            "$filter": " and ".join(filters),
            "$select": _HDR_SELECT,
            "$orderby": "PlannedDeliveryUTCDateTime desc",
            "$top": str(capped),
        }
        result = await s4.get_v4(
            f"{_SRV}/WhseOutboundDeliveryOrderHead", params=params, user_identity=user_id
        )
        rows = _results(result)
        if not rows:
            return f"No EWM outbound delivery orders found for warehouse {ewm_warehouse}."
        lines = [f"EWM Outbound Delivery Orders — WH {ewm_warehouse} (top {len(rows)}):"]
        for r in rows:
            lines.append(
                f"  ODO: {r.get('EWMOutboundDeliveryOrder','')}  "
                f"Type: {r.get('EWMDeliveryDocumentType','') or '-'}  "
                f"ShipTo: {r.get('ShipToParty','') or '-'} {r.get('ShipToPartyName','') or ''}  "
                f"Route: {r.get('EWMRoute','') or '-'}  "
                f"Status: {ODO_STATUS.get(r.get('EWMShippingReadinessStatus',''), r.get('EWMShippingReadinessStatus','') or '-')}  "
                f"PlannedDlv: {r.get('PlannedDeliveryUTCDateTime','') or '-'}"
            )
        return "\n".join(lines)

    return StructuredTool(
        name="get_ewm_outbound_deliveries",
        description=(
            "List EWM Outbound Delivery Orders for a warehouse. "
            "Filter by ship-to party. "
            "Returns ODO number, type, ship-to, route, shipping readiness status, planned delivery date."
        ),
        args_schema=GetEWMOutboundDeliveriesInput,
        coroutine=get_ewm_outbound_deliveries,
    )


def make_get_ewm_outbound_delivery_items(s4: "Client", user_id: str | None = None) -> StructuredTool:
    async def get_ewm_outbound_delivery_items(
        ewm_warehouse: str,
        outbound_delivery_order: str,
    ) -> str:
        params: dict[str, Any] = {
            "$filter": (
                f"EWMWarehouse eq '{ewm_warehouse}' and "
                f"EWMOutboundDeliveryOrder eq '{outbound_delivery_order}'"
            ),
            "$select": (
                "EWMWarehouse,EWMOutboundDeliveryOrder,EWMOutboundDeliveryOrderItem,"
                "Product,Batch,ProductQuantity,QuantityUnit,"
                "GoodsIssueStatus,PickingStatus,CompletionStatus,"
                "EWMStorageType,EWMStorageSection,WarehouseProcessType"
            ),
            "$top": str(MAX_PAGE_SIZE),
        }
        result = await s4.get_v4(
            f"{_SRV}/WhseOutboundDeliveryOrderItem", params=params, user_identity=user_id
        )
        rows = _results(result)
        if not rows:
            return f"No items found for EWM outbound delivery order {outbound_delivery_order}."
        lines = [f"Items for EWM Outbound Delivery Order {outbound_delivery_order}:"]
        for r in rows:
            gi = r.get("GoodsIssueStatus", "")
            lines.append(
                f"  Item: {r.get('EWMOutboundDeliveryOrderItem','')}  "
                f"Product: {r.get('Product','')}  "
                f"Batch: {r.get('Batch','') or '-'}  "
                f"Qty: {r.get('ProductQuantity','')} {r.get('QuantityUnit','')}  "
                f"GI: {ODO_STATUS.get(gi, gi) or '-'}  "
                f"Pick: {r.get('PickingStatus','') or '-'}  "
                f"Done: {r.get('CompletionStatus','') or '-'}"
            )
        return "\n".join(lines)

    return StructuredTool(
        name="get_ewm_outbound_delivery_items",
        description=(
            "Retrieve line items for an EWM Outbound Delivery Order. "
            "Shows product, batch, quantity, goods issue status, picking status, and completion status per item."
        ),
        args_schema=GetEWMOutboundDeliveryItemsInput,
        coroutine=get_ewm_outbound_delivery_items,
    )
