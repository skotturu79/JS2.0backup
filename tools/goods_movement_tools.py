"""Goods movement tools: material document history, goods receipt, and STO transfer posting.

Service roots:
  MATDOC_ROOT = /sap/opu/odata/sap/API_MATERIAL_DOCUMENT_SRV  (V2)
  PO_SRV      = /sap/opu/odata4/sap/api_purchaseorder_2/...   (V4, STO create)
"""
from __future__ import annotations

import json
import logging
import datetime
from typing import TYPE_CHECKING, Any

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from s4hana_client import Client

logger = logging.getLogger(__name__)

MATDOC_ROOT = "/sap/opu/odata/sap/API_MATERIAL_DOCUMENT_SRV"
INBDEL_ROOT = "/sap/opu/odata/sap/API_INBOUND_DELIVERY_SRV;v=0002"
PO_SRV = "/sap/opu/odata4/sap/api_purchaseorder_2/srvd_a2x/sap/api_purchaseorder_2/0001"
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

class GetMaterialDocumentsInput(BaseModel):
    material: str = Field(description="SAP material number")
    plant: str = Field(description="SAP plant code")
    batch: str = Field(default="", description="Batch number (optional)")
    movement_type: str = Field(
        default="",
        description="Filter by movement type, e.g. 101 (GR), 201 (GI), 551 (scrapping)",
    )
    top: int = Field(default=50, description="Max documents to return (max 100)")


class PostGoodsReceiptInput(BaseModel):
    delivery_document: str = Field(description="Inbound delivery document number")
    plant: str = Field(description="Receiving plant code")


# ---------------------------------------------------------------------------
# Tool factories
# ---------------------------------------------------------------------------

def make_get_material_documents(s4: "Client", user_id: str | None = None) -> StructuredTool:
    async def get_material_documents(
        material: str,
        plant: str,
        batch: str = "",
        movement_type: str = "",
        top: int = 50,
    ) -> str:
        capped = min(top, MAX_PAGE_SIZE)
        filter_parts = [f"Material eq '{material}'", f"Plant eq '{plant}'"]
        if batch:
            filter_parts.append(f"Batch eq '{batch}'")
        if movement_type:
            filter_parts.append(f"GoodsMovementType eq '{movement_type}'")
        params = _fmt({
            "$filter": " and ".join(filter_parts),
            "$select": (
                "MaterialDocument,MaterialDocumentYear,MaterialDocumentItem,"
                "GoodsMovementType,Material,Plant,StorageLocation,Batch,"
                "QuantityInBaseUnit,MaterialBaseUnit,FiscalYear,"
                "PurchaseOrder,Delivery"
            ),
            "$orderby": "MaterialDocument desc",
            "$top": str(capped),
        })
        result = await s4.get(
            f"{MATDOC_ROOT}/A_MaterialDocumentItem",
            params=params,
            user_identity=user_id,
        )
        rows = _results(result)
        if not rows:
            return f"No material documents found for material {material} at plant {plant}."
        lines = [f"Material Documents for {material} / Plant {plant} (top {capped}):"]
        for r in rows:
            lines.append(
                f"  Doc: {r.get('MaterialDocument','')}/{r.get('MaterialDocumentYear','')} "
                f"Item: {r.get('MaterialDocumentItem','')}  "
                f"Mvt: {r.get('GoodsMovementType','')}  "
                f"Batch: {r.get('Batch','') or '-'}  "
                f"Qty: {r.get('QuantityInBaseUnit','')} {r.get('MaterialBaseUnit','')}  "
                f"PO: {r.get('PurchaseOrder','') or '-'}  "
                f"Delivery: {r.get('Delivery','') or '-'}"
            )
        return "\n".join(lines)

    return StructuredTool(
        name="get_material_documents",
        description=(
            "Retrieve goods movement history (material documents) for a material at a plant. "
            "Optionally filter by batch or movement type (101=GR, 201=GI to cost center, "
            "261=GI to production order, 501=receipt w/o ref, 551=scrapping). "
            "Returns doc number, movement type, batch, quantity, posting date, PO and delivery reference."
        ),
        args_schema=GetMaterialDocumentsInput,
        coroutine=get_material_documents,
    )


def make_post_goods_receipt(s4: "Client", user_id: str | None = None) -> StructuredTool:
    async def post_goods_receipt(delivery_document: str, plant: str) -> str:
        """Post goods receipt (mvt 101) against an inbound delivery. REQUIRES USER CONFIRMATION."""
        body: dict[str, Any] = {
            "GoodsMovementCode": "01",
            "VersionForPrintingSlip": "0",
            "to_MaterialDocumentItem": {
                "results": [
                    {
                        "ReferenceDocumentType": "EL",
                        "ReferenceDocument": delivery_document,
                        "Plant": plant,
                    }
                ]
            },
        }
        result = await s4.post(
            f"{MATDOC_ROOT}/A_MaterialDocumentHeader",
            body=body,
            service_root=MATDOC_ROOT,
            user_identity=user_id,
        )
        if isinstance(result, dict) and result.get("error"):
            return f"Goods receipt posting failed: {result.get('message', result)}"
        if isinstance(result, dict):
            mat_doc = result.get("MaterialDocument", "")
            year = result.get("MaterialDocumentYear", "")
            if mat_doc:
                return (
                    f"Goods receipt posted successfully.\n"
                    f"  Material Document : {mat_doc}/{year}\n"
                    f"  Delivery          : {delivery_document}\n"
                    f"  Plant             : {plant}\n"
                    f"  Movement Type     : 101"
                )
        return json.dumps(result, indent=2)

    return StructuredTool(
        name="post_goods_receipt",
        description=(
            "Post goods receipt (movement type 101) against an inbound delivery. "
            "REQUIRES EXPLICIT USER CONFIRMATION before calling. "
            "Returns material document number on success."
        ),
        args_schema=PostGoodsReceiptInput,
        coroutine=post_goods_receipt,
    )


# ---------------------------------------------------------------------------
# STO transfer without delivery — create STO, GI 351, GR 101
# ---------------------------------------------------------------------------
#
# Core coroutines shared by the individual step tools AND the one-shot
# composite tool. Each returns a structured dict:
#   {"ok": bool, "doc": str, "year": str, "detail": str, "error": str}
# so callers can format their own output and chain steps.
# ---------------------------------------------------------------------------


def _norm_material(material: str) -> str:
    mat = material.upper().strip()
    if mat.isdigit():
        mat = mat.zfill(18)
    return mat


async def _create_sto_core(
    s4: "Client",
    user_id: str | None,
    *,
    po_type: str,
    purchasing_org: str,
    purchasing_group: str,
    company_code: str,
    supplying_plant: str,
    material: str,
    receiving_plant: str,
    receiving_sloc: str,
    quantity: float,
    unit: str,
) -> dict[str, Any]:
    rfc_params: dict[str, Any] = {
        "IV_PO_TYPE":   po_type.upper(),
        "IV_PURCH_ORG": purchasing_org.upper(),
        "IV_PUR_GROUP": purchasing_group,
        "IV_COMP_CODE": company_code.upper(),
        "IV_PLANT_SUP": f"PLANT_{supplying_plant.upper()}",
        "IV_MATERIAL":  _norm_material(material),
        "IV_PLANT_REC": receiving_plant.upper(),
        "IV_STGE_LOC":  receiving_sloc.upper() if receiving_sloc else "",
        "IV_QUANTITY":  quantity,
        "IV_UNIT":      unit.upper(),
    }
    result = await s4.call_rfc_soap("Z_CREATE_STO", rfc_params, user_identity=user_id)
    if isinstance(result, dict) and result.get("error"):
        return {"ok": False, "doc": "", "year": "", "detail": "", "error": str(result.get("message", result))}
    po_num = (result.get("EV_PO_NUMBER") or "").strip()
    if po_num:
        return {"ok": True, "doc": po_num, "year": "", "detail": "", "error": ""}
    et_return = result.get("ET_RETURN") or []
    errors = [r.get("MESSAGE", "") for r in et_return if isinstance(r, dict) and r.get("TYPE") in ("E", "A")]
    if errors:
        return {"ok": False, "doc": "", "year": "", "detail": "", "error": "; ".join(errors)}
    ev_msg = (result.get("EV_MESSAGE") or "").strip()
    if ev_msg:
        return {"ok": False, "doc": "", "year": "", "detail": "", "error": ev_msg}
    return {"ok": False, "doc": "", "year": "", "detail": "", "error": f"no details: {result}"}


async def _goods_movement_core(
    s4: "Client",
    user_id: str | None,
    *,
    gm_code: str,
    move_type: str,
    plant: str,
    stge_loc: str,
    material: str,
    quantity: float,
    unit: str,
    sto_number: str,
    sto_item: str,
    mvt_ind: str = "",
) -> dict[str, Any]:
    today = datetime.date.today().strftime("%Y%m%d")
    item: dict[str, Any] = {
        "PLANT": plant.upper(),
        "STGE_LOC": stge_loc.upper(),
        "MOVE_TYPE": move_type,
        "MATERIAL": _norm_material(material),
        "ENTRY_QNT": str(quantity),
        "ENTRY_UOM": unit.upper(),
        "PO_NUMBER": sto_number,
        "PO_ITEM": sto_item.zfill(5),
    }
    if mvt_ind:
        item["MVT_IND"] = mvt_ind
    rfc_params: dict[str, Any] = {
        "GOODSMVT_HEADER": {"PSTNG_DATE": today, "DOC_DATE": today},
        "GOODSMVT_CODE": {"GM_CODE": gm_code},
        "GOODSMVT_ITEM": [item],
        # SAP's /sap/bc/soap/rfc handler only serializes a TABLES param in the
        # response if it is present in the request. RETURN is output-only, so we
        # send it empty to force SAP to echo it back (with the ZDOC row).
        "RETURN": [],
    }
    result = await s4.call_rfc_soap("Z_GOODSMVT_POST4", rfc_params, user_identity=user_id)
    if isinstance(result, dict) and result.get("error"):
        return {"ok": False, "doc": "", "year": "", "detail": "", "error": str(result.get("message", result))}
    return_table = result.get("RETURN") or []
    if isinstance(return_table, dict):
        return_table = [return_table]
    zdoc = next((r for r in return_table if r.get("ID") == "ZDOC"), None)
    mat_doc = (zdoc.get("MESSAGE_V1") or "").strip() if zdoc else ""
    year = (zdoc.get("MESSAGE_V2") or "").strip() if zdoc else ""
    if mat_doc:
        return {"ok": True, "doc": mat_doc, "year": year, "detail": "", "error": ""}
    errors = [r.get("MESSAGE", r.get("MESSAGE_V1", "")) for r in return_table if r.get("TYPE") in ("E", "A")]
    if errors:
        return {"ok": False, "doc": "", "year": "", "detail": "", "error": "; ".join(errors)}
    logger.warning("%s RFC returned no mat doc. Result: %s", move_type, result)
    return {"ok": False, "doc": "", "year": "", "detail": "", "error": f"no material document returned: {result}"}


class CreateSTOInput(BaseModel):
    po_type: str = Field(default="ZIC3", description="STO document type: ZIC3 (default FGF inter-company STO)")
    purchasing_org: str = Field(default="PKG", description="Purchasing organization — default 'PKG' for D4H-200")
    purchasing_group: str = Field(default="DIR", description="Purchasing group — default 'DIR' for D4H-200")
    company_code: str = Field(default="2100", description="Company code — default '2100' for D4H-200")
    supplying_plant: str = Field(description="Supplying/issuing plant code (e.g. 'PRO6'). SAP encodes as Supplier=PLANT_{supplying_plant}.")
    material: str = Field(description="Material number to transfer")
    receiving_plant: str = Field(description="Receiving/destination plant code (e.g. 'FEN1')")
    receiving_sloc: str = Field(default="", description="Receiving storage location (leave blank for plant default)")
    quantity: float = Field(description="Order quantity")
    unit: str = Field(description="Unit of measure (e.g. 'KG', 'EA', 'CS')")


def make_create_sto(s4: "Client", user_id: str | None = None) -> StructuredTool:
    async def create_sto(
        po_type: str = "ZIC3",
        purchasing_org: str = "PKG",
        purchasing_group: str = "DIR",
        company_code: str = "2100",
        supplying_plant: str = "",
        material: str = "",
        receiving_plant: str = "",
        receiving_sloc: str = "",
        quantity: float = 0.0,
        unit: str = "",
    ) -> str:
        """Create a Stock Transport Order (STO) via Z_CREATE_STO RFC. REQUIRES USER CONFIRMATION."""
        res = await _create_sto_core(
            s4, user_id,
            po_type=po_type, purchasing_org=purchasing_org, purchasing_group=purchasing_group,
            company_code=company_code, supplying_plant=supplying_plant, material=material,
            receiving_plant=receiving_plant, receiving_sloc=receiving_sloc,
            quantity=quantity, unit=unit,
        )
        if not res["ok"]:
            return f"STO creation failed: {res['error']}"
        return (
            f"STO created successfully.\n"
            f"  STO Number      : {res['doc']}\n"
            f"  Type            : {po_type.upper()}\n"
            f"  Supplying Plant : {supplying_plant.upper()}\n"
            f"  Receiving Plant : {receiving_plant.upper()}\n"
            f"  Material        : {material.upper()}\n"
            f"  Quantity        : {quantity} {unit.upper()}"
        )

    return StructuredTool(
        name="create_sto",
        description=(
            "Create a Stock Transport Order (STO) for non-batch material transfer between plants. "
            "REQUIRES EXPLICIT USER CONFIRMATION before calling. "
            "FGF STO types: ZIC2 or ZIC3. Supplier field is auto-set to PLANT-{supplying_plant}. "
            "Use get_purchase_orders(is_sto=True) to verify the created STO afterwards. "
            "Returns the STO number on success."
        ),
        args_schema=CreateSTOInput,
        coroutine=create_sto,
    )


class PostSTOGoodsIssueInput(BaseModel):
    sto_number: str = Field(description="STO/PO number (e.g. '4800015073')")
    sto_item: str = Field(default="00010", description="STO item number (default '00010')")
    material: str = Field(description="Material number")
    supplying_plant: str = Field(description="Supplying/issuing plant code (e.g. 'PRO6')")
    supplying_sloc: str = Field(default="2100", description="Supplying storage location — default '2100' for PRO6 on D4H-200")
    quantity: float = Field(description="Quantity to issue")
    unit: str = Field(description="Unit of measure (e.g. 'KG', 'EA')")


def make_post_sto_goods_issue(s4: "Client", user_id: str | None = None) -> StructuredTool:
    async def post_sto_goods_issue(
        sto_number: str,
        sto_item: str = "00010",
        material: str = "",
        supplying_plant: str = "",
        supplying_sloc: str = "",
        quantity: float = 0.0,
        unit: str = "",
    ) -> str:
        """Post GI mvt 351 against STO via Z_GOODSMVT_POST4 SOAP RFC. REQUIRES USER CONFIRMATION."""
        supplying_sloc = supplying_sloc or "2100"
        res = await _goods_movement_core(
            s4, user_id,
            gm_code="03", move_type="351",
            plant=supplying_plant, stge_loc=supplying_sloc,
            material=material, quantity=quantity, unit=unit,
            sto_number=sto_number, sto_item=sto_item,
        )
        if not res["ok"]:
            return f"GI 351 posting failed: {res['error']}"
        return (
            f"Goods Issue posted successfully.\n"
            f"  Material Document : {res['doc']}/{res['year']}\n"
            f"  STO               : {sto_number} / Item {sto_item}\n"
            f"  Supplying Plant   : {supplying_plant.upper()} / SLoc {supplying_sloc.upper()}\n"
            f"  Material          : {material.upper()}  Qty: {quantity} {unit.upper()}\n"
            f"  Movement Type     : 351 (GI for STO — stock moves to in-transit)"
        )

    return StructuredTool(
        name="post_sto_goods_issue",
        description=(
            "Post Goods Issue (movement type 351) against a Stock Transport Order — no inbound delivery required. "
            "Issues stock from supplying plant into stock-in-transit. "
            "REQUIRES EXPLICIT USER CONFIRMATION before calling. "
            "Call post_sto_goods_receipt_no_del afterwards to complete the transfer at the receiving plant. "
            "Returns material document number on success."
        ),
        args_schema=PostSTOGoodsIssueInput,
        coroutine=post_sto_goods_issue,
    )


class PostSTOGoodsReceiptNoDelvInput(BaseModel):
    sto_number: str = Field(description="STO/PO number (e.g. '4800015073')")
    sto_item: str = Field(default="00010", description="STO item number (default '00010')")
    material: str = Field(description="Material number")
    receiving_plant: str = Field(description="Receiving/destination plant code (e.g. 'FEN1')")
    receiving_sloc: str = Field(default="2000", description="Receiving storage location — default '2000' for FEN1 on D4H-200")
    quantity: float = Field(description="Quantity to receive")
    unit: str = Field(description="Unit of measure (e.g. 'KG', 'EA')")


def make_post_sto_goods_receipt_no_del(s4: "Client", user_id: str | None = None) -> StructuredTool:
    async def post_sto_goods_receipt_no_del(
        sto_number: str,
        sto_item: str = "00010",
        material: str = "",
        receiving_plant: str = "",
        receiving_sloc: str = "",
        quantity: float = 0.0,
        unit: str = "",
    ) -> str:
        """Post GR mvt 101 against STO via Z_GOODSMVT_POST4 SOAP RFC. REQUIRES USER CONFIRMATION."""
        receiving_sloc = receiving_sloc or "2000"
        res = await _goods_movement_core(
            s4, user_id,
            gm_code="01", move_type="101", mvt_ind="B",
            plant=receiving_plant, stge_loc=receiving_sloc,
            material=material, quantity=quantity, unit=unit,
            sto_number=sto_number, sto_item=sto_item,
        )
        if not res["ok"]:
            return f"GR 101 posting failed: {res['error']}"
        return (
            f"Goods Receipt posted successfully.\n"
            f"  Material Document : {res['doc']}/{res['year']}\n"
            f"  STO               : {sto_number} / Item {sto_item}\n"
            f"  Receiving Plant   : {receiving_plant.upper()} / SLoc {receiving_sloc.upper()}\n"
            f"  Material          : {material.upper()}  Qty: {quantity} {unit.upper()}\n"
            f"  Movement Type     : 101 (GR against STO — stock in receiving plant)"
        )

    return StructuredTool(
        name="post_sto_goods_receipt_no_del",
        description=(
            "Post Goods Receipt (movement type 101) against a Stock Transport Order — no inbound delivery required. "
            "Receives stock from in-transit into the receiving plant storage location. "
            "REQUIRES EXPLICIT USER CONFIRMATION before calling. "
            "Use after post_sto_goods_issue to complete the STO transfer flow. "
            "For EWM-managed plants, EWM putaway tasks are created automatically — check get_warehouse_tasks afterwards. "
            "Returns material document number on success."
        ),
        args_schema=PostSTOGoodsReceiptNoDelvInput,
        coroutine=post_sto_goods_receipt_no_del,
    )


# ---------------------------------------------------------------------------
# One-shot composite: create STO -> GI 351 -> GR 101 in a single tool call
# ---------------------------------------------------------------------------

class ExecuteSTOTransferInput(BaseModel):
    material: str = Field(description="Material number to transfer (e.g. '1313284')")
    quantity: float = Field(description="Quantity to transfer")
    unit: str = Field(description="Unit of measure (e.g. 'KG', 'EA', 'CS')")
    supplying_plant: str = Field(default="PRO6", description="Supplying/issuing (3PL) plant code — default 'PRO6'")
    receiving_plant: str = Field(default="FEN1", description="Receiving/destination plant code — default 'FEN1'")
    supplying_sloc: str = Field(default="2100", description="Supplying storage location — default '2100' (PRO6 on D4H-200)")
    receiving_sloc: str = Field(default="2000", description="Receiving storage location — default '2000' (FEN1 on D4H-200)")
    po_type: str = Field(default="ZIC3", description="STO document type — default 'ZIC3' (FGF inter-company STO)")
    purchasing_org: str = Field(default="PKG", description="Purchasing organization — default 'PKG'")
    purchasing_group: str = Field(default="DIR", description="Purchasing group — default 'DIR'")
    company_code: str = Field(default="2100", description="Company code — default '2100'")
    sto_item: str = Field(default="00010", description="STO item number — default '00010'")


def make_execute_sto_transfer(s4: "Client", user_id: str | None = None) -> StructuredTool:
    async def execute_sto_transfer(
        material: str,
        quantity: float,
        unit: str,
        supplying_plant: str = "PRO6",
        receiving_plant: str = "FEN1",
        supplying_sloc: str = "2100",
        receiving_sloc: str = "2000",
        po_type: str = "ZIC3",
        purchasing_org: str = "PKG",
        purchasing_group: str = "DIR",
        company_code: str = "2100",
        sto_item: str = "00010",
    ) -> str:
        """Run the full STO transfer (create -> GI 351 -> GR 101) in one shot.

        Executes all three steps sequentially, stopping at the first failure and
        reporting exactly what completed. REQUIRES ONE up-front user confirmation;
        does NOT ask again between steps.
        """
        supplying_sloc = supplying_sloc or "2100"
        receiving_sloc = receiving_sloc or "2000"
        qty_disp = f"{quantity} {unit.upper()}"

        # Step 1 — create STO
        sto = await _create_sto_core(
            s4, user_id,
            po_type=po_type, purchasing_org=purchasing_org, purchasing_group=purchasing_group,
            company_code=company_code, supplying_plant=supplying_plant, material=material,
            receiving_plant=receiving_plant, receiving_sloc=receiving_sloc,
            quantity=quantity, unit=unit,
        )
        if not sto["ok"]:
            return (
                "STO transfer FAILED at step 1 (create STO). No documents were posted.\n"
                f"  Error : {sto['error']}"
            )
        sto_number = sto["doc"]

        # Step 2 — Goods Issue mvt 351 (stock -> in-transit)
        gi = await _goods_movement_core(
            s4, user_id,
            gm_code="03", move_type="351",
            plant=supplying_plant, stge_loc=supplying_sloc,
            material=material, quantity=quantity, unit=unit,
            sto_number=sto_number, sto_item=sto_item,
        )
        if not gi["ok"]:
            return (
                "STO transfer PARTIALLY complete — stopped at step 2 (GI 351).\n"
                f"  STO created       : {sto_number}\n"
                f"  GI 351 error      : {gi['error']}\n"
                "  Stock has NOT left the supplying plant. No GR was attempted.\n"
                f"  To retry the GI:  post_sto_goods_issue(sto_number='{sto_number}', material='{material.upper()}', "
                f"supplying_plant='{supplying_plant.upper()}', quantity={quantity}, unit='{unit.upper()}')"
            )

        # Step 3 — Goods Receipt mvt 101 (in-transit -> receiving plant)
        gr = await _goods_movement_core(
            s4, user_id,
            gm_code="01", move_type="101", mvt_ind="B",
            plant=receiving_plant, stge_loc=receiving_sloc,
            material=material, quantity=quantity, unit=unit,
            sto_number=sto_number, sto_item=sto_item,
        )
        if not gr["ok"]:
            return (
                "STO transfer PARTIALLY complete — stopped at step 3 (GR 101).\n"
                f"  STO created       : {sto_number}\n"
                f"  GI 351 posted     : {gi['doc']}/{gi['year']} (stock is now in-transit)\n"
                f"  GR 101 error      : {gr['error']}\n"
                f"  To retry the GR:  post_sto_goods_receipt_no_del(sto_number='{sto_number}', material='{material.upper()}', "
                f"receiving_plant='{receiving_plant.upper()}', quantity={quantity}, unit='{unit.upper()}')"
            )

        # All three succeeded
        return (
            "Stock transfer completed successfully (STO → GI 351 → GR 101).\n"
            "\n"
            "Result Summary\n"
            "==============\n"
            f"  Material          : {material.upper()}   Qty: {qty_disp}\n"
            f"  Route             : {supplying_plant.upper()}/{supplying_sloc.upper()} → {receiving_plant.upper()}/{receiving_sloc.upper()}\n"
            f"  STO ({po_type.upper()})       : {sto_number} / Item {sto_item}\n"
            f"  GI Mat Doc (351)  : {gi['doc']}/{gi['year']}   (stock issued to in-transit)\n"
            f"  GR Mat Doc (101)  : {gr['doc']}/{gr['year']}   (stock received at {receiving_plant.upper()})\n"
            "\n"
            f"If {receiving_plant.upper()} is EWM-managed, putaway tasks were created — check get_warehouse_tasks."
        )

    return StructuredTool(
        name="execute_sto_transfer",
        description=(
            "ONE-SHOT stock transfer between plants without delivery: creates the STO, posts Goods Issue "
            "(mvt 351) and posts Goods Receipt (mvt 101) in a single call, in sequence. "
            "Use this when the user wants the whole 3PL→FEN1 (PRO6→FEN1) transfer done in one step. "
            "REQUIRES ONE EXPLICIT USER CONFIRMATION before calling — after that, do NOT ask again between steps. "
            "Defaults target D4H-200 (supplying PRO6/SLoc 2100, receiving FEN1/SLoc 2000, type ZIC3, "
            "org PKG, group DIR, company 2100); override any of them for other routes. "
            "Stops at the first failed step and reports exactly which documents were posted so the user can recover. "
            "Returns the STO number plus both material document numbers on full success."
        ),
        args_schema=ExecuteSTOTransferInput,
        coroutine=execute_sto_transfer,
    )
