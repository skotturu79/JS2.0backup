"""Purchase Order / STO tools — OData V4.

Service: API_PURCHASEORDER_2
Path:    /sap/opu/odata4/sap/api_purchaseorder_2/srvd_a2x/sap/api_purchaseorder_2/0001

FGF PO types:
  ZNB  — Standard external PO
  ZRET — Return PO
  ZIC2 — Inter-company STO (Supplier = PLANT-xxx)
  ZIC3 — Inter-company STO (Supplier = PLANT-xxx)
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from s4hana_client import Client

logger = logging.getLogger(__name__)

_SRV = "/sap/opu/odata4/sap/api_purchaseorder_2/srvd_a2x/sap/api_purchaseorder_2/0001"

STO_TYPES = {"ZIC2", "ZIC3"}
PO_TYPE_LABELS = {
    "ZNB":  "Standard PO",
    "ZRET": "Return PO",
    "ZIC2": "Inter-Company STO",
    "ZIC3": "Inter-Company STO",
}


def _results(payload: Any) -> tuple[list[dict], str]:
    if isinstance(payload, dict):
        err = payload.get("error")
        if err:
            msg = err.get("message", {}) if isinstance(err, dict) else str(err)
            text = msg.get("value", str(msg)) if isinstance(msg, dict) else str(msg)
            return [], f"SAP error [{err.get('code','') if isinstance(err,dict) else ''}]: {text}"
        return payload.get("value", []), ""
    if isinstance(payload, list):
        return payload, ""
    return [], ""


def _supplying_plant(supplier: str) -> str:
    """PLANT-BAR1 → BAR1"""
    if supplier.startswith("PLANT-"):
        return supplier[6:]
    return supplier


# ── Tool 1: Search / list purchase orders ───────────────────────────────────

class GetPurchaseOrdersInput(BaseModel):
    po_number: str = Field(default="", description="Exact PO number (e.g. '4800015063')")
    po_type: str = Field(default="", description="PO document type: ZNB=Standard, ZRET=Return, ZIC2/ZIC3=STO. Leave blank for all.")
    is_sto: bool = Field(default=False, description="If true, return only Stock Transport Orders (ZIC2+ZIC3)")
    supplier: str = Field(default="", description="Supplier/vendor number (for external POs) or PLANT-xxx (for STOs)")
    supplying_plant: str = Field(default="", description="Supplying plant code for STOs (e.g. 'BAR1', 'ORM2'). Translates to Supplier=PLANT-xxx.")
    purchasing_org: str = Field(default="", description="Purchasing organization (e.g. 'ING', 'PKG')")
    date_from: str = Field(default="", description="Creation date from (YYYY-MM-DD)")
    date_to: str = Field(default="", description="Creation date to (YYYY-MM-DD)")
    top: int = Field(default=20, description="Max records to return (max 100)")


def make_get_purchase_orders(s4: "Client", user_id: str | None = None) -> StructuredTool:
    async def get_purchase_orders(
        po_number: str = "",
        po_type: str = "",
        is_sto: bool = False,
        supplier: str = "",
        supplying_plant: str = "",
        purchasing_org: str = "",
        date_from: str = "",
        date_to: str = "",
        top: int = 20,
    ) -> str:
        filters: list[str] = []

        if po_number:
            filters.append(f"PurchaseOrder eq '{po_number}'")
        if po_type:
            filters.append(f"PurchaseOrderType eq '{po_type.upper()}'")
        elif is_sto:
            filters.append("(PurchaseOrderType eq 'ZIC2' or PurchaseOrderType eq 'ZIC3')")
        if supplying_plant:
            filters.append(f"Supplier eq 'PLANT-{supplying_plant.upper()}'")
        elif supplier:
            filters.append(f"Supplier eq '{supplier}'")
        if purchasing_org:
            filters.append(f"PurchasingOrganization eq '{purchasing_org}'")
        if date_from:
            filters.append(f"CreationDate ge {date_from}")
        if date_to:
            filters.append(f"CreationDate le {date_to}")

        params: dict[str, Any] = {
            "$top": str(min(top, 100)),
            "$orderby": "PurchaseOrder desc",
            "$select": (
                "PurchaseOrder,PurchaseOrderType,Supplier,PurchasingOrganization,"
                "PurchasingGroup,DocumentCurrency,CreationDate,CompanyCode,"
                "PaymentTerms,IncotermsClassification"
            ),
            "$format": "json",
        }
        if filters:
            params["$filter"] = " and ".join(filters)

        result = await s4.get_v4(f"{_SRV}/PurchaseOrder", params=params, user_identity=user_id)
        rows, err = _results(result)
        if err:
            return err
        if not rows:
            return "No purchase orders found for the given criteria."

        lines = [f"Purchase Orders ({len(rows)} found):"]
        lines.append(f"{'PO Number':<14} {'Type':<6} {'Type Label':<22} {'Supplier/Plant':<22} {'POrg':<6} {'Currency':<5} {'Created'}")
        lines.append("-" * 95)
        for r in rows:
            potype = r.get("PurchaseOrderType", "")
            supp = r.get("Supplier", "") or "-"
            label = PO_TYPE_LABELS.get(potype, potype)
            display_supp = _supplying_plant(supp) if supp.startswith("PLANT-") else supp
            lines.append(
                f"{r.get('PurchaseOrder',''):<14} "
                f"{potype:<6} "
                f"{label:<22} "
                f"{display_supp:<22} "
                f"{r.get('PurchasingOrganization',''):<6} "
                f"{r.get('DocumentCurrency',''):<5} "
                f"{str(r.get('CreationDate',''))[:10]}"
            )
        return "\n".join(lines)

    return StructuredTool(
        name="get_purchase_orders",
        description=(
            "Search and list Purchase Orders and Stock Transport Orders (STOs) from SAP. "
            "FGF PO types: ZNB=Standard external PO, ZRET=Return PO, ZIC2/ZIC3=Inter-Company STO. "
            "Use is_sto=true to list only STOs. "
            "Use supplying_plant to find STOs from a specific plant (e.g. 'BAR1', 'ORM2'). "
            "Filter by date range (YYYY-MM-DD), purchasing org, or exact PO number. "
            "Returns header list with PO number, type, supplier/plant, org, currency, date."
        ),
        args_schema=GetPurchaseOrdersInput,
        coroutine=get_purchase_orders,
    )


# ── Tool 2: Get PO/STO full details (header + items) ────────────────────────

class GetPODetailsInput(BaseModel):
    po_number: str = Field(description="PO or STO number (e.g. '4800015063')")


def make_get_po_details(s4: "Client", user_id: str | None = None) -> StructuredTool:
    async def get_po_details(po_number: str) -> str:
        import asyncio

        # Fetch header and items concurrently
        params_hdr: dict[str, Any] = {
            "$filter": f"PurchaseOrder eq '{po_number}'",
            "$format": "json",
        }
        params_items: dict[str, Any] = {
            "$filter": f"PurchaseOrder eq '{po_number}'",
            "$select": (
                "PurchaseOrder,PurchaseOrderItem,Material,MaterialGroup,Plant,"
                "StorageLocation,OrderQuantity,PurchaseOrderQuantityUnit,BaseUnit,"
                "NetPriceAmount,NetAmount,DocumentCurrency,PurchaseOrderItemText,"
                "GoodsReceiptIsExpected,IsCompletelyDelivered,IsReturnsItem,"
                "PurchasingDocumentDeletionCode,PurchasingItemIsFreeOfCharge,"
                "ItemGrossWeight,ItemWeightUnit,PurgDocPriceDate"
            ),
            "$format": "json",
        }

        hdr_res, items_res = await asyncio.gather(
            s4.get_v4(f"{_SRV}/PurchaseOrder", params=params_hdr, user_identity=user_id),
            s4.get_v4(f"{_SRV}/PurchaseOrderItem", params=params_items, user_identity=user_id),
        )

        hdrs, err1 = _results(hdr_res)
        items, err2 = _results(items_res)

        if err1:
            return err1
        if not hdrs:
            return f"PO {po_number} not found."

        h = hdrs[0]
        potype = h.get("PurchaseOrderType", "")
        supp = h.get("Supplier", "") or "-"
        is_sto = potype in STO_TYPES
        label = PO_TYPE_LABELS.get(potype, potype)

        lines = [
            f"{'STO' if is_sto else 'Purchase Order'} Details — {po_number}",
            f"  Type          : {potype} ({label})",
        ]
        if is_sto:
            lines.append(f"  Supplying Plant: {_supplying_plant(supp)}")
        else:
            lines.append(f"  Supplier       : {supp}")
        lines += [
            f"  Purchasing Org : {h.get('PurchasingOrganization','')}  Group: {h.get('PurchasingGroup','')}",
            f"  Company Code   : {h.get('CompanyCode','')}",
            f"  Currency       : {h.get('DocumentCurrency','')}",
            f"  Created        : {str(h.get('CreationDate',''))[:10]}",
            f"  Payment Terms  : {h.get('PaymentTerms','') or '-'}",
            "",
            f"Items ({len(items)}):",
            f"  {'Item':<6} {'Material':<20} {'Descr':<30} {'Plant':<6} {'SLoc':<6} {'OrderQty':>10} {'Unit':<5} {'NetAmt':>12} {'GR?':<4} {'Done?'}",
            "  " + "-" * 105,
        ]
        if err2:
            lines.append(f"  (Items error: {err2})")
        else:
            for r in items:
                lines.append(
                    f"  {r.get('PurchaseOrderItem',''):<6} "
                    f"{r.get('Material',''):<20} "
                    f"{(r.get('PurchaseOrderItemText','') or '')[:30]:<30} "
                    f"{r.get('Plant',''):<6} "
                    f"{r.get('StorageLocation','') or '-':<6} "
                    f"{float(r.get('OrderQuantity') or 0):>10.3f} "
                    f"{r.get('PurchaseOrderQuantityUnit',''):<5} "
                    f"{float(r.get('NetAmount') or r.get('NetPriceAmount') or 0):>12.2f} "
                    f"{'Y' if r.get('GoodsReceiptIsExpected') else 'N':<4} "
                    f"{'Y' if r.get('IsCompletelyDelivered') else 'N'}"
                )
        return "\n".join(lines)

    return StructuredTool(
        name="get_po_details",
        description=(
            "Get full details of a Purchase Order or STO including header and all line items. "
            "Returns PO type, supplier/supplying plant, org, dates, and per-item material, "
            "plant, storage location, ordered qty, open qty, delivery date, net amount, and GR status. "
            "Use get_purchase_orders first to find the PO number."
        ),
        args_schema=GetPODetailsInput,
        coroutine=get_po_details,
    )
