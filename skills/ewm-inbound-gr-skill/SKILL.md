---
name: ewm-inbound-gr-skill
description: "Post a Goods Receipt against an EWM inbound delivery. Full GR (all open items) and partial GR (specific items/quantities) use the standard SAP Warehouse Inbound Delivery A2X OData V4 API (API_WAREHOUSE_INBOUNDDELIVERY). Handling-unit (HU) level GR — post GR for one or more specific HUs, not the whole delivery — uses the custom RFC-enabled function module Z_EWM_GR_HU_POST. This is the EWM-owned goods-receipt path, distinct from the IM/STO route (movement type 101) and from the LE/ERP inbound delivery service (API_INBOUND_DELIVERY_SRV, V2)."
---

# EWM Inbound Delivery — Goods Receipt (Full / Partial / HU)

Post a goods receipt against an **EWM inbound delivery**. Full and partial GR go through the standard
**Warehouse Inbound Delivery (A2X), OData V4** service; **HU-level** GR goes through the custom
RFC-enabled FM **`Z_EWM_GR_HU_POST`**. Use this when EWM owns the warehouse and the GR is posted
against a delivery document (not the IM/STO movement-type route).

## System Context
- **Service (full/partial):** Warehouse Inbound Delivery (A2X), OData V4 — `API_WAREHOUSE_INBOUNDDELIVERY`
- **Root:** `/sap/opu/odata4/sap/api_warehouseinbounddelivery/srvd_a2x/sap/warehouseinbounddelivery/0001/`
- **Entities:** `WarehouseInboundDelivery` / `WarehouseInboundDeliveryItem`
- **Action:** bound **Post Goods Receipt** on the header
- **HU-level GR:** custom FM `Z_EWM_GR_HU_POST` (function group `ZEWM_GRH`), RFC-enabled, invoked over
  SOAP-RFC (`/sap/bc/soap/rfc`) on the existing connectivity channel. Wraps `/SCDL/CL_SP_PRD_INB` with
  action `/SCWM/IF_SP_C=>SC_ACT_HU_POST_GM` — posts GR for only the requested handling units.
- **Client:** data/execution on client 200 (standard API). The custom FM is ABAP code built on client 100
  but is cross-client callable, so it operates on client-200 delivery data through the client-200 destination.

## When to Use This vs. Other GR Tools
| Situation | Tool |
|-----------|------|
| EWM-managed warehouse, GR against an inbound **delivery** | **this skill** (`post_ewm_inbound_gr`) |
| STO / IM route, non-batch transfer (movement type 101) | `post_sto_goods_receipt_no_del` / `execute_sto_transfer` (sto-nodel-skill) |
| Just reading LE/ERP inbound deliveries | `get_inbound_deliveries` (API_INBOUND_DELIVERY_SRV, V2) |

## Available Tools
| Tool | Action |
|------|--------|
| `get_ewm_inbound_delivery` | Read header + items (keys, open qty, unit) from the A2X V4 service. Use BEFORE a partial GR. |
| `post_ewm_inbound_gr` | Post the GR. `mode='full'` (all open items), `mode='partial'` (given items/quantities), or pass `handling_unit` / `handling_units` for HU-level GR. |

## GR Modes
- **Full** — `post_ewm_inbound_gr(inbound_delivery, mode='full')`. Posts open quantity for **all** items (empty action body).
- **Partial** — `post_ewm_inbound_gr(inbound_delivery, mode='partial', items=[{item, quantity, unit}, ...])`.
  Sends PATCH-quantity + Post-Goods-Receipt as **one `$batch` changeset** (atomic, correctly ordered).
- **Handling Unit (HU)** — pass one HU (`handling_unit='...'`) or several (`handling_units=['...','...']`).
  Posts GR for **only those HUs** via the custom FM `Z_EWM_GR_HU_POST` (SOAP-RFC), independent of how many
  HUs the delivery item has — e.g. a delivery item with 10 HUs can have GR posted for just 2. The delivery
  number is required; if the caller supplies HUs without a delivery, the agent resolves HU→delivery from the
  mapping service (and, if that service is unavailable, asks for the delivery). Set `test_run=True` for a
  dry-run (IV_TESTRUN='X') that validates without posting.

## Flow
### Step 1 — Identify the delivery (and items for partial, or HUs for HU-level)
- Ask for the inbound delivery number.
- For a **partial** GR, call `get_ewm_inbound_delivery(inbound_delivery)` first to get exact item keys, open quantities, and units. Never guess item numbers or quantities.
- For an **HU-level** GR, collect the specific handling-unit ID(s). If the user gives only HUs (no delivery), the agent will resolve the delivery from the HU where possible.

### Step 2 — Single Confirmation Block
Show ONE confirmation block and wait for **yes**:
```
Goods Receipt Summary — Please Confirm
======================================
Service         : Warehouse Inbound Delivery (A2X, OData V4) | Z_EWM_GR_HU_POST (HU-level)
Inbound Delivery: {inbound_delivery}
Mode            : {full | partial | handling unit}
Items           : {ALL open items | list of item=qty unit | HU(s): id1, id2}

Confirm? (yes / no)
```

### Step 3 — Post (after confirmation)
```
post_ewm_inbound_gr(inbound_delivery, mode="full")
# or
post_ewm_inbound_gr(inbound_delivery, mode="partial",
                    items=[{"item": "10", "quantity": 5, "unit": "KG"}])
# or — HU-level: post GR for one or more specific handling units
post_ewm_inbound_gr(inbound_delivery, handling_units=["HU0001", "HU0002"])
post_ewm_inbound_gr(inbound_delivery, handling_unit="HU0001", test_run=True)  # dry-run
```
Relay the tool's returned result verbatim, then suggest verifying with `get_ewm_inbound_delivery`.

## Rules
- ONE confirmation block up front — do not re-ask per item.
- For partial GR, read the delivery first; use exact item keys, open quantities, and units.
- For HU-level GR, pass the exact HU IDs; the FM ALPHA-normalizes them, so send raw values (no zero-padding).
- Relay SAP error messages **verbatim** — do NOT auto-retry write operations.
- If the bound-action name or quantity field is rejected, the message will name the value used
  (default action `SAP__self.PostGoodsReceipt`, qty field `QuantityToPost`). Confirm the correct names
  from `$metadata` and pass `action_name` / `qty_field` / `qty_unit_field` overrides — do not guess repeatedly.
- HU-level GR relays the FM's BAPIRET2 messages verbatim; `EV_REJECTED='X'` means nothing was posted.

## Error Handling
| Error | Action |
|-------|--------|
| Action name / qty field mismatch (HTTP 4xx from SAP) | Relay verbatim; fetch `$metadata`, retry once with `action_name`/`qty_field` overrides |
| `$batch` per-request failure (partial) | Tool reports the failing request(s); relay verbatim, no commit occurred |
| ICF node / service not active | Relay the SAP/gateway error; the A2X V4 service must be activated on the target system |
| HU given without a delivery, mapping service down | Tool asks for the delivery number — relay and ask the user |
| HU maps to multiple deliveries | Tool lists them and refuses — ask the user which delivery |
| HU-level GR rejected (`EV_REJECTED='X'`) | Relay the FM's BAPIRET2 messages verbatim; nothing was posted |
