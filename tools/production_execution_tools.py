"""Production execution write tools — GI to order, operation confirmation, GR from order.

Services (OData V2):
  API_MATERIAL_DOCUMENT_SRV      /sap/opu/odata/sap/API_MATERIAL_DOCUMENT_SRV  (GI/GR)
  API_PROD_ORDER_CONFIRMATION_2  /sap/opu/odata/sap/API_PROD_ORDER_CONFIRMATION_2 (confirmation)

All tools REQUIRE EXPLICIT USER CONFIRMATION before executing.
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

_MATDOC_SRV = "/sap/opu/odata/sap/API_MATERIAL_DOCUMENT_SRV"
_CONF2_SRV = "/sap/opu/odata/sap/API_PROD_ORDER_CONFIRMATION_2"


def _pad_order(v: str) -> str:
    return v.zfill(12) if v.isdigit() else v


# ---------------------------------------------------------------------------
# Input schemas
# ---------------------------------------------------------------------------

class PostGoodsIssueProductionInput(BaseModel):
    production_order: str = Field(description="Production order number")
    material: str = Field(description="Material/component number to issue")
    plant: str = Field(description="Plant code (e.g. '1710')")
    storage_location: str = Field(description="Storage location to issue from (e.g. '171A')")
    quantity: float = Field(description="Quantity to issue")
    unit_of_measure: str = Field(description="Base unit of measure (e.g. 'KG', 'EA', 'L')")
    batch: str = Field(default="", description="Batch number (optional)")
    reservation: str = Field(default="", description="Reservation document number (optional — from get_production_order_components)")
    reservation_item: str = Field(default="", description="Reservation item (optional, e.g. '0001')")


class PostProductionConfirmationInput(BaseModel):
    production_order: str = Field(description="Production order number")
    operation: str = Field(description="Operation number (e.g. '0010') — from get_production_order_operations")
    yield_quantity: float = Field(description="Confirmed yield quantity")
    unit_of_measure: str = Field(description="Unit of measure matching the production unit (e.g. 'EA', 'KG')")
    scrap_quantity: float = Field(default=0.0, description="Scrap quantity (default 0)")
    is_final_confirmation: bool = Field(default=False, description="True = final confirmation (closes the operation)")
    posting_date: str = Field(default="", description="Posting date YYYYMMDD (default = today)")


class PostGoodsReceiptProductionInput(BaseModel):
    production_order: str = Field(description="Production order number")
    material: str = Field(description="Finished good / material being produced")
    plant: str = Field(description="Receiving plant code (e.g. '1710')")
    storage_location: str = Field(description="Destination storage location (e.g. '171A')")
    quantity: float = Field(description="Quantity to receive")
    unit_of_measure: str = Field(description="Unit of measure (e.g. 'EA', 'KG')")
    batch: str = Field(default="", description="Batch number for finished goods (optional)")


# ---------------------------------------------------------------------------
# Tool factories
# ---------------------------------------------------------------------------

def make_post_goods_issue_production(s4: "Client", user_id: str | None = None) -> StructuredTool:
    async def post_goods_issue_production(
        production_order: str,
        material: str,
        plant: str,
        storage_location: str,
        quantity: float,
        unit_of_measure: str,
        batch: str = "",
        reservation: str = "",
        reservation_item: str = "",
    ) -> str:
        """Post goods issue (mvt 261) of a component to a production order. REQUIRES USER CONFIRMATION."""
        item: dict[str, Any] = {
            "Material": material,
            "Plant": plant,
            "StorageLocation": storage_location,
            "GoodsMovementType": "261",
            "QuantityInBaseUnit": str(quantity),
            "BaseUnit": unit_of_measure,
            "ManufacturingOrder": _pad_order(production_order),
        }
        if batch:
            item["Batch"] = batch
        if reservation:
            item["Reservation"] = reservation.zfill(10) if reservation.isdigit() else reservation
        if reservation_item:
            item["ReservationItem"] = reservation_item.zfill(4) if reservation_item.isdigit() else reservation_item

        body: dict[str, Any] = {
            "GoodsMovementCode": "03",
            "to_MaterialDocumentItem": {"results": [item]},
        }
        result = await s4.post(
            f"{_MATDOC_SRV}/A_MaterialDocumentHeader",
            body=body,
            service_root=_MATDOC_SRV,
            user_identity=user_id,
        )
        if isinstance(result, dict) and result.get("error"):
            return f"Goods issue posting failed: {result.get('message', result)}"
        if isinstance(result, dict):
            mat_doc = result.get("MaterialDocument", "")
            year = result.get("MaterialDocumentYear", "")
            if mat_doc:
                return (
                    f"Goods issue posted successfully.\n"
                    f"  Material Document : {mat_doc}/{year}\n"
                    f"  Production Order  : {production_order}\n"
                    f"  Material          : {material}\n"
                    f"  Qty Issued        : {quantity} {unit_of_measure}\n"
                    f"  Storage Location  : {storage_location}\n"
                    f"  Movement Type     : 261 (GI to Production Order)"
                )
        return json.dumps(result, indent=2)

    return StructuredTool(
        name="post_goods_issue_production",
        description=(
            "Post goods issue (movement type 261) of a component to a production order. "
            "Use get_production_order_components first to see the open required quantities "
            "and reservation numbers. Provide reservation/reservation_item if known "
            "to ensure correct reservation consumption. "
            "REQUIRES EXPLICIT USER CONFIRMATION before calling. "
            "Returns material document number on success."
        ),
        args_schema=PostGoodsIssueProductionInput,
        coroutine=post_goods_issue_production,
    )


def make_post_production_confirmation(s4: "Client", user_id: str | None = None) -> StructuredTool:
    async def post_production_confirmation(
        production_order: str,
        operation: str,
        yield_quantity: float,
        unit_of_measure: str,
        scrap_quantity: float = 0.0,
        is_final_confirmation: bool = False,
        posting_date: str = "",
    ) -> str:
        """Confirm a production order operation with yield/scrap quantities. REQUIRES USER CONFIRMATION."""
        padded = _pad_order(production_order)
        op_padded = operation.zfill(4) if operation.isdigit() else operation

        body: dict[str, Any] = {
            "ProductionOrder": padded,
            "ManufacturingOrderOperation": op_padded,
            "ManufacturingOrderSequence": "0",
            "ConfirmationYieldQuantity": str(yield_quantity),
            "ConfirmationScrapQuantity": str(scrap_quantity),
            "ConfirmationUnit": unit_of_measure,
            "IsFinalConfirmation": is_final_confirmation,
        }
        if posting_date:
            body["PostingDate"] = posting_date

        result = await s4.post(
            f"{_CONF2_SRV}/A_ProductionOrderConf",
            body=body,
            service_root=_CONF2_SRV,
            user_identity=user_id,
        )
        if isinstance(result, dict) and result.get("error"):
            return f"Production confirmation failed: {result.get('message', result)}"
        if isinstance(result, dict):
            conf_no = result.get("ProductionOrderConfirmation", "")
            if conf_no:
                final_str = " (FINAL — operation closed)" if is_final_confirmation else ""
                return (
                    f"Production confirmation posted successfully.\n"
                    f"  Confirmation No   : {conf_no}\n"
                    f"  Production Order  : {production_order}\n"
                    f"  Operation         : {operation}\n"
                    f"  Yield Quantity    : {yield_quantity} {unit_of_measure}{final_str}\n"
                    f"  Scrap Quantity    : {scrap_quantity} {unit_of_measure}\n"
                    f"  Final Confirmation: {'Yes' if is_final_confirmation else 'No'}"
                )
        return json.dumps(result, indent=2)

    return StructuredTool(
        name="post_production_confirmation",
        description=(
            "Confirm a production order operation with actual yield and scrap quantities. "
            "Use get_production_order_operations first to get the operation number. "
            "Set is_final_confirmation=True to close the operation after the last piece. "
            "Partial confirmations are allowed — call multiple times for partial deliveries. "
            "REQUIRES EXPLICIT USER CONFIRMATION before calling. "
            "Returns confirmation document number on success."
        ),
        args_schema=PostProductionConfirmationInput,
        coroutine=post_production_confirmation,
    )


def make_post_goods_receipt_production(s4: "Client", user_id: str | None = None) -> StructuredTool:
    async def post_goods_receipt_production(
        production_order: str,
        material: str,
        plant: str,
        storage_location: str,
        quantity: float,
        unit_of_measure: str,
        batch: str = "",
    ) -> str:
        """Post goods receipt (mvt 101) of finished goods from a production order. REQUIRES USER CONFIRMATION."""
        item: dict[str, Any] = {
            "Material": material,
            "Plant": plant,
            "StorageLocation": storage_location,
            "GoodsMovementType": "101",
            "QuantityInBaseUnit": str(quantity),
            "BaseUnit": unit_of_measure,
            "ManufacturingOrder": _pad_order(production_order),
            "GoodsMovementRefDocType": "PP",
        }
        if batch:
            item["Batch"] = batch

        body: dict[str, Any] = {
            "GoodsMovementCode": "02",
            "to_MaterialDocumentItem": {"results": [item]},
        }
        result = await s4.post(
            f"{_MATDOC_SRV}/A_MaterialDocumentHeader",
            body=body,
            service_root=_MATDOC_SRV,
            user_identity=user_id,
        )
        if isinstance(result, dict) and result.get("error"):
            return f"Goods receipt from production failed: {result.get('message', result)}"
        if isinstance(result, dict):
            mat_doc = result.get("MaterialDocument", "")
            year = result.get("MaterialDocumentYear", "")
            if mat_doc:
                return (
                    f"Goods receipt from production posted successfully.\n"
                    f"  Material Document : {mat_doc}/{year}\n"
                    f"  Production Order  : {production_order}\n"
                    f"  Material          : {material}\n"
                    f"  Qty Received      : {quantity} {unit_of_measure}\n"
                    f"  Storage Location  : {storage_location}\n"
                    f"  Batch             : {batch or '(auto-assigned)'}\n"
                    f"  Movement Type     : 101 (GR from Production Order)"
                )
        return json.dumps(result, indent=2)

    return StructuredTool(
        name="post_goods_receipt_production",
        description=(
            "Post goods receipt (movement type 101) of finished goods from a production order. "
            "Use after production is confirmed. EWM will automatically create putaway warehouse tasks. "
            "REQUIRES EXPLICIT USER CONFIRMATION before calling. "
            "Returns material document number on success."
        ),
        args_schema=PostGoodsReceiptProductionInput,
        coroutine=post_goods_receipt_production,
    )
