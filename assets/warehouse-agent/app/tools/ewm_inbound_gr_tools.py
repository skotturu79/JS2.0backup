"""EWM Inbound Delivery — Goods Receipt posting via the standard SAP API.

Service: Warehouse Inbound Delivery (A2X), OData V4
  Binding       : API_WHSE_INB_DELIVERY_2 (published V4)  |  SRVD: API_WHSE_INBOUND_DELIVERY_2 v0001
  Root          : /sap/opu/odata4/sap/api_whse_inb_delivery_2/srvd_a2x/sap/warehouseinbounddelivery/0001/
  Entities      : WhseInboundDeliveryHead / WhseInboundDeliveryItem  (key fields EWMInboundDelivery / EWMInboundDeliveryItem)
  Action        : SAP__self.PostGoodsReceipt (bound to the header, param _it)

GR modes:
  - full    : POST the bound PostGoodsReceipt action with an empty body → posts open qty for all items.
  - partial : PATCH the to-be-posted qty on the given item(s), then POST the action — sent as ONE
              $batch changeset so the update+post is atomic and correctly ordered.
  - HU       : Post at the HANDLING-UNIT level. The standard A2X API exposes NO HU-scoped GR action —
              it can only receive a whole delivery (all items) or per-item quantities, never "these 2
              of the 10 HUs on this line". So the HU path calls a CUSTOM RFC function module
              Z_EWM_GR_HU_POST3 (function group ZEWM_HR, created on client 100 in $TMP, callable
              system-wide since ABAP repository objects are cross-client). Given an inbound delivery
              plus one or more HU numbers, it drives the EWM PRD delivery service provider
              (/SCDL/CL_SP_PRD_INB, HU aspect → action /SCWM/IF_SP_C=>SC_ACT_HU_POST_GM) to post GR for
              ONLY those HUs, leaving the delivery's other HUs / lines open, and returns BAPIRET2
              messages + EV_REJECTED. It is invoked over SOAP RFC (/sap/bc/soap/rfc), the same channel
              used for Z_GOODSMVT_POST4. When the delivery number isn't supplied, the HU is first
              resolved to its inbound delivery via a small CUSTOM OData V4 mapping service
              (CDS ZC_EWM_HU_INB_DLV → SRVD ZSRVD_EWM_HU_INB_DLV → SRVB ZSRVB_EWM_HU_INB_DLV,
              HUIDENT → EWMInboundDelivery, inbound DOCCAT 'PDI'); if that mapping service isn't
              published yet, the tool asks for the delivery number instead of guessing. Both the FM
              name and the mapping service's root/entity/field names are overridable via environment
              variables (see below) so they can be corrected without a redeploy.

The exact bound-action qualified name and the item quantity property vary by release — confirm from
$metadata. Both are overridable per call (action_name / qty_field / qty_unit_field) so a mismatch can
be corrected without a redeploy. SAP messages are relayed verbatim; write ops are never auto-retried.

REQUIRES EXPLICIT USER CONFIRMATION before calling — this posts a real goods receipt.
"""
from __future__ import annotations

import json
import logging
import os
from typing import TYPE_CHECKING, Any

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from s4hana_client import Client

logger = logging.getLogger(__name__)

# Service root (trailing slash — entity paths append directly).
# Published V4 binding API_WHSE_INB_DELIVERY_2 (SRVD API_WHSE_INBOUND_DELIVERY_2), verified live on D4H-200.
_SRV_ROOT = "/sap/opu/odata4/sap/api_whse_inb_delivery_2/srvd_a2x/sap/warehouseinbounddelivery/0001/"
_HEADER_ENTITY = "WhseInboundDeliveryHead"
_ITEM_ENTITY = "WhseInboundDeliveryItem"

# Key field names (entity-set names differ from key property names in this service).
_HEADER_KEY_FIELD = "EWMInboundDelivery"
_ITEM_KEY_FIELD = "EWMInboundDeliveryItem"

# ASN reference on the header. NOTE: AdvancedShippingNotification is FREE TEXT and NOT unique —
# several deliveries can share the same value (e.g. "PACKING SLIP 1"), so an ASN lookup may match
# more than one delivery. When it does, we list the matches and refuse to post until one is chosen.
_ASN_FIELD = "AdvancedShippingNotification"

# Defaults — confirmed against live $metadata (API_WHSE_INBOUND_DELIVERY_2 v0001).
# PostGoodsReceipt is bound to the header (param _it); empty body posts open qty for all items.
_ACTION_DEFAULT = "SAP__self.PostGoodsReceipt"
# Partial-GR quantity fields on the item. NOTE: the released path to change to-be-posted qty is the
# item-bound action SAP__self.AdjustDeliveryItemQuantity; a plain PATCH of ProductQuantity may be
# rejected. These are overridable per call. ProductQuantity/QuantityUnit are the real item properties.
_QTY_FIELD_DEFAULT = "ProductQuantity"
_QTY_UNIT_FIELD_DEFAULT = "QuantityUnit"

# ---------------------------------------------------------------------------
# HU → inbound-delivery mapping service (CUSTOM, projected — not yet published).
# The standard Warehouse Inbound Delivery A2X service exposes NO handling-unit field, so an HU
# number cannot be resolved through it. This maps HUIDENT → EWMInboundDelivery via a small custom
# CDS view (ZC_EWM_HU_INB_DLV, inbound DOCCAT 'PDI') exposed as an OData V4 service:
#     CDS  ZC_EWM_HU_INB_DLV   (HandlingUnit, EWMInboundDelivery, EWMWarehouse,
#                               AdvancedShippingNotification, DeliveryCategory)
#     SRVD ZSRVD_EWM_HU_INB_DLV  exposes it as entity  HandlingUnitInbDelivery
#     SRVB ZSRVB_EWM_HU_INB_DLV  (OData V4) — created in ADT on client 100, PUBLISHED on client 200.
#
# Until that binding is published, the HU path returns a clear "not published yet" message and posts
# nothing. Everything below is OVERRIDABLE via environment variables so the tool can be flipped on —
# or a URL segment corrected — WITHOUT a redeploy (just set the var in CF and restart):
#     HU_MAP_SRV_ROOT   full runtime root; CONFIRM the exact value from the published binding, e.g.
#                       /sap/opu/odata4/sap/zsrvb_ewm_hu_inb_dlv/srvd/sap/zsrvd_ewm_hu_inb_dlv/0001/
#     HU_MAP_ENTITY     entity set name        (default HandlingUnitInbDelivery)
#     HU_MAP_HU_FIELD   HU filter property     (default HandlingUnit)
#     HU_MAP_IBD_FIELD  delivery-number property (default EWMInboundDelivery)
_HU_SRV_ROOT = os.environ.get(
    "HU_MAP_SRV_ROOT",
    "/sap/opu/odata4/sap/zsrvb_ewm_hu_inb_dlv/srvd/sap/zsrvd_ewm_hu_inb_dlv/0001/",
)
_HU_ENTITY = os.environ.get("HU_MAP_ENTITY", "HandlingUnitInbDelivery")
_HU_FIELD = os.environ.get("HU_MAP_HU_FIELD", "HandlingUnit")
_HU_IBD_FIELD = os.environ.get("HU_MAP_IBD_FIELD", "EWMInboundDelivery")

# Custom HU-level GR function module — posts GR for SPECIFIC handling units of a delivery, leaving
# the delivery's other HUs/lines open (the standard A2X API can't do this). RFC-enabled, invoked over
# SOAP RFC. Interface: IV_DELIVERY (string), IV_TESTRUN (string, 'X'=validate only), IT_HU table of
# /SCWM/S_HUIDENT (field HUIDENT), ET_RETURN table of BAPIRET2, EV_REJECTED (string, 'X' on failure).
# Created in function group ZEWM_HR on client 100 ($TMP); callable system-wide (repository is
# cross-client) — it resolves & operates on client-200 delivery data through the client-200 destination.
# NOTE: every source line is kept <=72 chars because RPY_FUNCTIONMODULE_INSERT (the RFC create path)
# truncates source at 72 columns; longer lines silently break the generated function-pool load.
# Overridable so the name can be corrected without a redeploy.
_GR_HU_FM = os.environ.get("EWM_GR_HU_FM", "Z_EWM_GR_HU_POST3")

# Shown when the custom mapping service isn't reachable/published yet.
_HU_NOT_PUBLISHED_MSG = (
    "Handling-unit lookup isn't available yet: the HU→inbound-delivery mapping service "
    "(ZSRVB_EWM_HU_INB_DLV) hasn't been activated/published on the SAP system. Once an administrator "
    "publishes it (and confirms its OData root via the HU_MAP_SRV_ROOT setting), I'll be able to post a "
    "goods receipt straight from an HU number. In the meantime, give me the EWM inbound delivery number "
    "or the ASN / packing-slip reference and I'll proceed. Nothing was posted."
)

# Shown when HUs are given without a delivery and the HU→delivery mapping service can't resolve one.
# HU-level GR needs the delivery number (the custom FM matches the requested HUs against that delivery's
# HUs), so we ask for it rather than guessing.
_GR_HU_NEED_DELIVERY_MSG = (
    "To post a goods receipt for specific handling unit(s) I need the EWM inbound delivery they belong "
    "to — the handling-unit lookup service isn't available to resolve it automatically. Tell me the "
    "inbound delivery number (or its ASN / packing-slip reference) together with the HU number(s), and "
    "I'll receive just those HUs. Nothing was posted."
)


def _err_text(payload: dict, where: str) -> str:
    """Format a SAP error payload verbatim for the user."""
    status = payload.get("status_code", "?")
    msg = payload.get("message") or payload.get("raw") or payload
    return f"{where} failed (HTTP {status}):\n{msg}"


def _as_list(payload: Any) -> list[dict]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        if "error" in payload:
            return []
        inner = payload.get("value", payload)
        if isinstance(inner, list):
            return inner
        if isinstance(inner, dict):
            return [inner]
    return []


async def _resolve_deliveries_by_asn(s4: "Client", asn: str, user_id: str | None) -> tuple[list[dict], dict | None]:
    """Resolve an ASN (AdvancedShippingNotification) to matching delivery headers.

    Returns (rows, error_payload). rows = list of header dicts (may be 0, 1, or many —
    the ASN field is free text and not unique). On a service error, error_payload is the
    SAP error dict and rows is empty.
    """
    asn_esc = asn.replace("'", "''")
    resp = await s4.get_v4(
        f"{_SRV_ROOT}{_HEADER_ENTITY}",
        params={
            "$filter": f"{_ASN_FIELD} eq '{asn_esc}'",
            "$select": f"{_HEADER_KEY_FIELD},{_ASN_FIELD},EWMDeliveryDocumentType",
            "$top": "50",
        },
        user_identity=user_id,
    )
    if isinstance(resp, dict) and resp.get("error"):
        return [], resp
    return _as_list(resp), None


def _hu_service_unavailable(err: dict) -> bool:
    """True when the error looks like the custom HU-mapping service isn't published yet.

    Distinguishes a genuine service error (relay verbatim) from "the binding hasn't been
    activated/published on this system" (a 403/404/501/503 at the service group, or a
    not-found/service-group message) so we can show the friendly _HU_NOT_PUBLISHED_MSG.
    """
    try:
        status = int(err.get("status_code"))
    except (TypeError, ValueError):
        status = 0
    if status in (403, 404, 501, 503):
        return True
    blob = json.dumps(err, default=str).lower()
    return any(
        s in blob
        for s in (
            "resource not found",
            "not found",
            "service group",
            "not published",
            "does not exist",
            "no service found",
        )
    )


async def _resolve_deliveries_by_hu(s4: "Client", hu: str, user_id: str | None) -> tuple[list[str], dict | None]:
    """Resolve a Handling Unit number (HUIDENT) to distinct inbound-delivery numbers.

    Uses the custom HU→delivery mapping service. Returns (ibd_numbers, error_payload).
    ibd_numbers is a sorted list of DISTINCT EWMInboundDelivery values (normally 1). On a
    service error, error_payload is the SAP error dict and the list is empty — the caller
    checks _hu_service_unavailable() to decide between the friendly not-published message
    and relaying the error verbatim.
    """
    hu_esc = hu.replace("'", "''")
    resp = await s4.get_v4(
        f"{_HU_SRV_ROOT}{_HU_ENTITY}",
        params={
            "$filter": f"{_HU_FIELD} eq '{hu_esc}'",
            "$select": f"{_HU_IBD_FIELD},{_ASN_FIELD},EWMWarehouse",
            "$top": "50",
        },
        user_identity=user_id,
    )
    if isinstance(resp, dict) and resp.get("error"):
        return [], resp
    rows = _as_list(resp)
    ibds = sorted({str(r.get(_HU_IBD_FIELD, "")).strip() for r in rows if r.get(_HU_IBD_FIELD)})
    return ibds, None


def _bapiret_lines(rows: list[dict]) -> list[str]:
    """Format BAPIRET2 rows (from the SOAP-RFC response) into readable '[T] message' lines."""
    out: list[str] = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        t = (r.get("TYPE") or "").strip()
        msg = (r.get("MESSAGE") or "").strip()
        if not msg:  # some rows carry only the message variables
            msg = " ".join(
                v for v in (
                    (r.get("MESSAGE_V1") or "").strip(),
                    (r.get("MESSAGE_V2") or "").strip(),
                    (r.get("MESSAGE_V3") or "").strip(),
                    (r.get("MESSAGE_V4") or "").strip(),
                ) if v
            )
        if msg:
            out.append(f"[{t or '?'}] {msg}")
    return out


async def _post_gr_by_hu(
    s4: "Client", delivery: str, hus: list[str], test_run: bool, user_id: str | None
) -> tuple[bool, str]:
    """Post a HANDLING-UNIT-level goods receipt via the custom Z_EWM_GR_HU_POST3 RFC FM.

    Receives ONLY the given HUs of the delivery (other HUs/lines stay open). Returns
    (ok, message). ok=False means SAP rejected the post (EV_REJECTED='X' or an E/A message);
    the message relays SAP's BAPIRET2 text verbatim. Never auto-retried by the caller.
    """
    clean_hus = [str(h).strip() for h in hus if str(h).strip()]
    rfc_params: dict[str, Any] = {
        "IV_DELIVERY": str(delivery).strip(),
        "IV_TESTRUN": "X" if test_run else "",
        # Table of /SCWM/S_HUIDENT rows — the FM ALPHA-normalizes HUIDENT internally.
        "IT_HU": [{"HUIDENT": h} for h in clean_hus],
        # ET_RETURN is output-only; SAP's SOAP-RFC handler only echoes a TABLES param back
        # if it is present in the request, so send it empty to get the messages returned.
        "ET_RETURN": [],
    }
    result = await s4.call_rfc_soap(_GR_HU_FM, rfc_params, user_identity=user_id)
    if isinstance(result, dict) and result.get("error"):
        return False, _err_text(result, f"HU-level GR for delivery {delivery}")

    ret = result.get("ET_RETURN") or []
    if isinstance(ret, dict):
        ret = [ret]
    lines = _bapiret_lines(ret)
    rejected = (result.get("EV_REJECTED") or "").strip().upper() == "X"
    has_err = any(
        isinstance(r, dict) and (r.get("TYPE") or "").strip() in ("E", "A") for r in ret
    )
    hu_txt = ", ".join(clean_hus)
    msg_block = ("\n  " + "\n  ".join(lines)) if lines else ""

    if rejected or has_err:
        return False, (
            f"Goods receipt for handling unit(s) {hu_txt} on inbound delivery {delivery} was "
            f"NOT posted — SAP rejected it:{msg_block or ' (no message returned)'}\n"
            f"Relay these messages; nothing was committed."
        )
    if test_run:
        return True, (
            f"Test run OK for handling unit(s) {hu_txt} on inbound delivery {delivery} — the HU-level "
            f"goods receipt validated cleanly and was NOT posted (test run).{msg_block}"
        )
    return True, (
        f"Goods receipt posted at the handling-unit level for inbound delivery {delivery}. "
        f"Received handling unit(s): {hu_txt}. Other handling units / lines on the delivery remain "
        f"open. You can ask to see the delivery again to review the updated status.{msg_block}"
    )


# ---------------------------------------------------------------------------
# Read: header + items (find keys, open qty, HUs)
# ---------------------------------------------------------------------------

class GetEwmInboundDeliveryInput(BaseModel):
    inbound_delivery: str = Field(
        default="",
        description="EWM inbound delivery document number (WhseInboundDeliveryHead key). Provide this OR 'asn' OR 'handling_unit'.",
    )
    asn: str = Field(
        default="",
        description="ASN / packing-slip reference (AdvancedShippingNotification) to look the delivery up by, when the number isn't known.",
    )
    handling_unit: str = Field(
        default="",
        description="Handling unit number (HUIDENT) to look the inbound delivery up by, via the custom HU→delivery mapping service.",
    )


class ListEwmInboundDeliveriesInput(BaseModel):
    warehouse: str = Field(default="PBAR", description="EWM warehouse number (EWMWarehouse), e.g. PBAR")
    open_only: bool = Field(default=True, description="If true, return only deliveries not yet fully GR-posted")
    top: int = Field(default=20, description="Max deliveries to return (max 100)")


def make_list_ewm_inbound_deliveries(s4: "Client", user_id: str | None = None) -> StructuredTool:
    async def list_ewm_inbound_deliveries(
        warehouse: str = "PBAR", open_only: bool = True, top: int = 20
    ) -> str:
        """List EWM inbound delivery headers for a warehouse from the A2X V4 service."""
        wh = (warehouse or "PBAR").strip()
        capped = min(top, 100)
        params: dict[str, str] = {
            "$filter": f"EWMWarehouse eq '{wh}'",
            "$select": (
                "EWMInboundDelivery,EWMDeliveryDocumentType,EWMWarehouse,"
                "AdvancedShippingNotification,GoodsReceiptUTCDateTime,"
                "OverallGoodsMovementStatus,GoodsMovementStatus"
            ),
            "$orderby": "EWMInboundDelivery desc",
            "$top": str(capped),
        }
        resp = await s4.get_v4(
            f"{_SRV_ROOT}{_HEADER_ENTITY}",
            params=params,
            user_identity=user_id,
        )
        if isinstance(resp, dict) and resp.get("error"):
            return _err_text(resp, f"List EWM inbound deliveries for warehouse {wh}")
        rows = _as_list(resp)
        if not rows:
            return f"No EWM inbound deliveries found for warehouse {wh}."
        if open_only:
            rows = [r for r in rows if r.get("GoodsMovementStatus", "") != "C"]
            if not rows:
                return f"No open (not fully GR-posted) EWM inbound deliveries found for warehouse {wh}."
        lines = [f"EWM Inbound Deliveries for warehouse {wh} ({len(rows)} found, open_only={open_only}):"]
        for r in rows:
            gm_status = r.get("GoodsMovementStatus") or r.get("OverallGoodsMovementStatus") or ""
            lines.append(
                f"  {r.get('EWMInboundDelivery','')}  "
                f"Type: {r.get('EWMDeliveryDocumentType','')}  "
                f"ASN: {r.get('AdvancedShippingNotification','') or '-'}  "
                f"GR Status: {gm_status or '-'}"
            )
        return "\n".join(lines)

    return StructuredTool(
        name="list_ewm_inbound_deliveries",
        description=(
            "List EWM inbound delivery headers for a given warehouse from the standard "
            "Warehouse Inbound Delivery A2X OData V4 service. Filters by EWMWarehouse; "
            "open_only=true (default) hides fully-received deliveries. Use this to find "
            "inbound delivery numbers before calling get_ewm_inbound_delivery or post_ewm_inbound_gr. "
            "Distinct from the LE/ERP get_inbound_deliveries (API_INBOUND_DELIVERY_SRV V2)."
        ),
        args_schema=ListEwmInboundDeliveriesInput,
        coroutine=list_ewm_inbound_deliveries,
    )


def make_get_ewm_inbound_delivery(s4: "Client", user_id: str | None = None) -> StructuredTool:
    async def get_ewm_inbound_delivery(inbound_delivery: str = "", asn: str = "", handling_unit: str = "") -> str:
        """Read an EWM inbound delivery header + its items from the A2X V4 service."""
        ibd = (inbound_delivery or "").strip()
        asn = (asn or "").strip()
        hu = (handling_unit or "").strip()
        if not ibd and asn:
            rows, err = await _resolve_deliveries_by_asn(s4, asn, user_id)
            if err:
                return _err_text(err, f"ASN lookup '{asn}'")
            if not rows:
                return f"No inbound delivery found with ASN '{asn}'."
            if len(rows) > 1:
                listed = "\n".join(
                    f"    - {r.get(_HEADER_KEY_FIELD)} (type {r.get('EWMDeliveryDocumentType', '?')})"
                    for r in rows
                )
                return (
                    f"ASN '{asn}' matches {len(rows)} inbound deliveries:\n{listed}\n"
                    f"Tell me which EWM inbound delivery number to read."
                )
            ibd = str(rows[0].get(_HEADER_KEY_FIELD, "")).strip()
        if not ibd and hu:
            ibds, err = await _resolve_deliveries_by_hu(s4, hu, user_id)
            if err:
                if _hu_service_unavailable(err):
                    return _HU_NOT_PUBLISHED_MSG
                return _err_text(err, f"HU lookup '{hu}'")
            if not ibds:
                return f"No inbound delivery found for handling unit '{hu}'."
            if len(ibds) > 1:
                listed = "\n".join(f"    - {d}" for d in ibds)
                return (
                    f"Handling unit '{hu}' maps to {len(ibds)} inbound deliveries:\n{listed}\n"
                    f"Tell me which EWM inbound delivery number to read."
                )
            ibd = ibds[0]
        if not ibd:
            return "Provide an EWM inbound delivery number, an ASN (AdvancedShippingNotification), or a handling unit to read."
        header = await s4.get_v4(
            f"{_SRV_ROOT}{_HEADER_ENTITY}('{ibd}')",
            user_identity=user_id,
        )
        if isinstance(header, dict) and header.get("error"):
            return _err_text(header, f"Read inbound delivery {ibd}")

        items = await s4.get_v4(
            f"{_SRV_ROOT}{_ITEM_ENTITY}",
            params={"$filter": f"{_HEADER_KEY_FIELD} eq '{ibd}'", "$top": "200"},
            user_identity=user_id,
        )
        if isinstance(items, dict) and items.get("error"):
            return _err_text(items, f"Read items for inbound delivery {ibd}")

        rows = _as_list(items)
        lines = [f"EWM Inbound Delivery {ibd} (A2X V4):"]
        if isinstance(header, dict):
            lines.append(
                "  Header: " + json.dumps(
                    {k: v for k, v in header.items() if not k.startswith("@") and not k.startswith("_")},
                    default=str,
                )[:800]
            )
        lines.append(f"  Items ({len(rows)}):")
        for r in rows:
            lines.append(
                "    " + json.dumps(
                    {k: v for k, v in r.items() if not k.startswith("@") and not k.startswith("_")},
                    default=str,
                )[:600]
            )
        lines.append(
            "\nNote: use the item key + open quantity above to build a partial GR. You can also post a "
            "goods receipt for specific handling unit(s) of this delivery (HU-level GR via the custom "
            "Z_EWM_GR_HU_POST3 function module) — pass handling_unit / handling_units with this delivery."
        )
        return "\n".join(lines)

    return StructuredTool(
        name="get_ewm_inbound_delivery",
        description=(
            "Read an EWM inbound delivery (header + items) from the standard Warehouse Inbound Delivery "
            "A2X OData V4 service. Identify the delivery by its number (inbound_delivery), by its "
            "ASN / packing-slip reference (asn), or by a handling unit number (handling_unit, resolved "
            "via the custom HU→delivery mapping service). Use this to find item keys, open quantities, and "
            "units BEFORE posting a partial goods receipt. This is the EWM-owned service — distinct from the "
            "LE/ERP get_inbound_deliveries (API_INBOUND_DELIVERY_SRV, V2)."
        ),
        args_schema=GetEwmInboundDeliveryInput,
        coroutine=get_ewm_inbound_delivery,
    )


# ---------------------------------------------------------------------------
# Write: post goods receipt (full / partial / HU)
# ---------------------------------------------------------------------------

class GRItem(BaseModel):
    item: str = Field(description="Inbound delivery item number (WarehouseInboundDeliveryItem key, e.g. '10')")
    quantity: float = Field(description="Quantity to post (receive) for this item")
    unit: str = Field(default="", description="Unit of measure for the quantity (e.g. 'KG', 'PC')")


class PostEwmInboundGrInput(BaseModel):
    inbound_delivery: str = Field(
        default="",
        description="EWM inbound delivery document number (WhseInboundDeliveryHead key). Provide this OR 'asn' OR 'handling_unit'.",
    )
    asn: str = Field(
        default="",
        description=(
            "Advanced Shipping Notification / packing-slip reference on the delivery header. "
            "Used to LOOK UP the inbound delivery when the delivery number isn't known. "
            "It is free text and may match several deliveries — if so the tool lists them and posts nothing."
        ),
    )
    mode: str = Field(
        default="full",
        description="'full' = post open qty for ALL items (empty action body). 'partial' = post only the given items/quantities.",
    )
    items: list[GRItem] = Field(
        default_factory=list,
        description="Required for mode='partial': the items and quantities to receive. Ignored for mode='full'.",
    )
    handling_unit: str = Field(
        default="",
        description=(
            "A single handling unit number (HUIDENT) to receive. Posts a GR at the HANDLING-UNIT level "
            "via the custom Z_EWM_GR_HU_POST3 function module — ONLY this HU is received, other HUs/lines "
            "on the delivery stay open. Give the inbound delivery too (inbound_delivery or asn); if it's "
            "omitted the tool tries to resolve it from the HU via the mapping service. Use handling_units "
            "for more than one."
        ),
    )
    handling_units: list[str] = Field(
        default_factory=list,
        description=(
            "Two or more handling unit numbers (HUIDENT) to receive together at the HANDLING-UNIT level "
            "(e.g. post GR for 2 of the 10 HUs on a line). Only these HUs are received; the delivery's "
            "other HUs/lines remain open. Supply the inbound delivery (inbound_delivery or asn) they "
            "belong to."
        ),
    )
    test_run: bool = Field(
        default=False,
        description=(
            "HU-level GR only: when true, validate the handling-unit goods receipt without posting "
            "(test run) — the FM checks it and rolls back. Useful to preview before a real post."
        ),
    )
    action_name: str = Field(
        default="",
        description="Override the bound-action qualified name if $metadata differs (default 'SAP__self.PostGoodsReceipt').",
    )
    qty_field: str = Field(default="", description="Override the item quantity property name (default 'ProductQuantity').")
    qty_unit_field: str = Field(default="", description="Override the item quantity-unit property name (default 'QuantityUnit').")


def make_post_ewm_inbound_gr(s4: "Client", user_id: str | None = None) -> StructuredTool:
    async def post_ewm_inbound_gr(
        inbound_delivery: str = "",
        asn: str = "",
        mode: str = "full",
        items: list[dict] | None = None,
        handling_unit: str = "",
        handling_units: list[str] | None = None,
        test_run: bool = False,
        action_name: str = "",
        qty_field: str = "",
        qty_unit_field: str = "",
    ) -> str:
        """Post a goods receipt for an EWM inbound delivery (full / partial / HU-level) via A2X V4 or the custom HU FM."""
        ibd = (inbound_delivery or "").strip()
        asn = (asn or "").strip()
        # Merge the single + multi HU inputs into one de-duplicated, order-preserving list.
        hu_list: list[str] = []
        for h in ([handling_unit] if handling_unit else []) + list(handling_units or []):
            hs = str(h).strip()
            if hs and hs not in hu_list:
                hu_list.append(hs)
        resolved_from_hu = ""

        # Resolve the delivery from an ASN when the delivery number wasn't given directly.
        if not ibd and asn:
            rows, err = await _resolve_deliveries_by_asn(s4, asn, user_id)
            if err:
                return _err_text(err, f"ASN lookup '{asn}'")
            if not rows:
                return (
                    f"No inbound delivery found with ASN '{asn}'. Nothing posted. "
                    f"Check the ASN / packing-slip reference, or provide the EWM inbound delivery number directly."
                )
            if len(rows) > 1:
                listed = "\n".join(
                    f"    - {r.get(_HEADER_KEY_FIELD)} "
                    f"(type {r.get('EWMDeliveryDocumentType', '?')})"
                    for r in rows
                )
                return (
                    f"ASN '{asn}' matches {len(rows)} inbound deliveries — it is not unique, so I won't post blindly:\n"
                    f"{listed}\n"
                    f"Tell me which EWM inbound delivery number to receive, then I'll post the goods receipt."
                )
            ibd = str(rows[0].get(_HEADER_KEY_FIELD, "")).strip()

        # HU-LEVEL GR — receive ONLY the given handling unit(s) of the delivery via the custom FM.
        # This is the true HU-scoped path: other HUs / lines on the delivery stay open.
        if hu_list:
            if not ibd:
                # Delivery not supplied — try to resolve it from the first HU (best effort).
                ibds, err = await _resolve_deliveries_by_hu(s4, hu_list[0], user_id)
                if err:
                    if _hu_service_unavailable(err):
                        return _GR_HU_NEED_DELIVERY_MSG
                    return _err_text(err, f"HU lookup '{hu_list[0]}'")
                if not ibds:
                    return (
                        f"No inbound delivery found for handling unit '{hu_list[0]}'. Nothing posted. "
                        f"Give me the EWM inbound delivery number these HUs belong to."
                    )
                if len(ibds) > 1:
                    listed = "\n".join(f"    - {d}" for d in ibds)
                    return (
                        f"Handling unit '{hu_list[0]}' maps to {len(ibds)} inbound deliveries — not unique, "
                        f"so I won't post blindly:\n{listed}\n"
                        f"Tell me which EWM inbound delivery number these HUs belong to."
                    )
                ibd = ibds[0]
                resolved_from_hu = hu_list[0]
            ok, msg = await _post_gr_by_hu(s4, ibd, hu_list, test_run, user_id)
            prefix = (
                f"Handling unit {resolved_from_hu} belongs to inbound delivery {ibd}. "
                if resolved_from_hu else ""
            )
            return prefix + msg

        if not ibd:
            return (
                "No delivery specified. Provide an EWM inbound delivery number, an ASN "
                "(AdvancedShippingNotification) reference, or a handling unit. Nothing posted."
            )

        action = action_name.strip() or _ACTION_DEFAULT
        qf = qty_field.strip() or _QTY_FIELD_DEFAULT
        quf = qty_unit_field.strip() or _QTY_UNIT_FIELD_DEFAULT
        mode = (mode or "full").strip().lower()
        items = items or []

        action_path = f"{_SRV_ROOT}{_HEADER_ENTITY}('{ibd}')/{action}"

        # FULL GR — bound action, empty body, posts open qty for all items.
        # The header entity carries an ETag; SAP Gateway rejects a non-conditional POST with
        # HTTP 428, so send If-Match:* to satisfy the optimistic-concurrency check.
        if mode == "full":
            result = await s4.post_action_v4(
                action_path, body={}, service_root=_SRV_ROOT, user_identity=user_id,
                if_match="*",
            )
            if isinstance(result, dict) and result.get("error"):
                return _err_text(result, f"Full GR for inbound delivery {ibd}")
            return (
                f"Goods receipt posted successfully for inbound delivery {ibd}. "
                f"All open items have been received into the warehouse, and the delivery is "
                f"now marked goods-receipt complete. You can ask to see the delivery again to "
                f"review the updated item status."
            )

        # PARTIAL GR — PATCH item qty then POST action, in ONE $batch changeset (atomic + ordered).
        if mode == "partial":
            if not items:
                return "mode='partial' requires at least one item {item, quantity, unit}. Nothing posted."
            requests: list[dict] = []
            patch_ids: list[str] = []
            for idx, it in enumerate(items, start=1):
                # StructuredTool passes plain dicts; be tolerant of either shape.
                item_no = str(it["item"] if isinstance(it, dict) else it.item)
                qty = it["quantity"] if isinstance(it, dict) else it.quantity
                unit = (it.get("unit", "") if isinstance(it, dict) else it.unit) or ""
                body: dict[str, Any] = {qf: str(qty)}
                if unit:
                    body[quf] = unit
                pid = f"p{idx}"
                patch_ids.append(pid)
                requests.append({
                    "id": pid,
                    "method": "PATCH",
                    "url": f"{_ITEM_ENTITY}({_HEADER_KEY_FIELD}='{ibd}',{_ITEM_KEY_FIELD}='{item_no}')",
                    "headers": {"Content-Type": "application/json"},
                    "body": body,
                })
            requests.append({
                "id": "post",
                "dependsOn": patch_ids,
                "method": "POST",
                "url": f"{_HEADER_ENTITY}('{ibd}')/{action}",
                "headers": {"Content-Type": "application/json", "If-Match": "*"},
                "body": {},
            })
            batch_body = {"requests": requests}
            result = await s4.post_action_v4(
                f"{_SRV_ROOT}$batch", body=batch_body, service_root=_SRV_ROOT, user_identity=user_id
            )
            if isinstance(result, dict) and result.get("error"):
                return _err_text(result, f"Partial GR for inbound delivery {ibd}")
            # A $batch may return 200 with per-request results (including per-request errors).
            responses = result.get("responses") if isinstance(result, dict) else None
            if responses:
                bad = [r for r in responses if isinstance(r, dict) and int(r.get("status", 0)) >= 400]
                if bad:
                    return (
                        f"Partial GR for inbound delivery {ibd} had failures inside the $batch:\n"
                        f"{json.dumps(bad, default=str)[:800]}\n"
                        f"No commit — relay these SAP messages; do not auto-retry."
                    )
            item_summary = ", ".join(
                f"{(it['item'] if isinstance(it, dict) else it.item)}="
                f"{(it['quantity'] if isinstance(it, dict) else it.quantity)}"
                f"{(it.get('unit','') if isinstance(it, dict) else it.unit) or ''}"
                for it in items
            )
            return (
                f"Goods receipt posted successfully for inbound delivery {ibd}. "
                f"The following quantities have been received into the warehouse: {item_summary}. "
                f"You can ask to see the delivery again to review the updated item status."
            )

        return f"Unknown mode '{mode}'. Use 'full' or 'partial'. Nothing posted."

    return StructuredTool(
        name="post_ewm_inbound_gr",
        description=(
            "Post a Goods Receipt against an EWM inbound delivery. Three scopes:\n"
            "• mode='full' — receive open quantity for ALL items (standard A2X V4 bound action, empty body).\n"
            "• mode='partial' — receive only the given items/quantities (PATCH qty + action in one $batch "
            "changeset, atomic + ordered).\n"
            "• HANDLING-UNIT level — pass handling_unit (one) or handling_units (several) to receive ONLY "
            "those HUs of the delivery, leaving its other HUs/lines open (e.g. GR 2 of the 10 HUs on a "
            "line). This uses the custom Z_EWM_GR_HU_POST3 function module over RFC — the standard API "
            "cannot scope a GR to specific HUs. Give the inbound delivery (inbound_delivery or asn) with "
            "the HU(s); if omitted the tool tries to resolve it from the HU via the mapping service and "
            "otherwise asks for it. test_run=true validates the HU GR without posting.\n"
            "Identify the delivery by number (inbound_delivery) or ASN / packing-slip reference (asn) — an "
            "ASN or HU matching more than one delivery is listed and nothing is posted until you pick one. "
            "This is the EWM-owned GR path; for the IM/STO route use post_sto_goods_receipt_no_del instead. "
            "REQUIRES EXPLICIT USER CONFIRMATION before calling — it posts a real goods receipt. "
            "Relay any SAP message verbatim; do NOT auto-retry."
        ),
        args_schema=PostEwmInboundGrInput,
        coroutine=post_ewm_inbound_gr,
    )
