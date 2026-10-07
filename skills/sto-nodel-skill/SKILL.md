---
name: sto-nodel-skill
description: "Stock transfer from 3PL to FEN1 via IM (Inventory Management). Moves non-batch material from the 3PL supplying plant (PRO6) to receiving plant FEN1 using a Stock Transport Order without inbound delivery — full flow: create STO (ZIC3) → post GI movement 351 → post GR movement 101. IM route (movement types 351/101), NOT EWM/delivery-based. Used when batch management is not required and no delivery document exists."
---

# Stock Transfer from 3PL to FEN1 Via IM (STO Without Delivery)

Transfers material from the **3PL supplying plant (PRO6)** to **receiving plant FEN1** via
**Inventory Management** (goods movements 351/101 against an STO) — no inbound delivery, no EWM
delivery document. Use this when batch management is not required.

## System Context
- **System:** D4H-200 — client 200
- **Route:** 3PL plant PRO6 → FEN1, via IM (movement types 351/101). NOT the EWM/delivery route.
- **FGF STO Type:** ZIC3 (inter-company Stock Transport Order — default for FGF)
- **Supplier encoding:** Supplying plant PRO6 → `Supplier = PLANT_PRO6` (underscore, not hyphen)
- **GI Movement Type:** 351 — GI from supplying plant (stock moves to in-transit)
- **GR Movement Type:** 101 — GR at receiving plant (stock arrives from in-transit)
- **API (GI/GR):** `Z_GOODSMVT_POST4` SOAP RFC (single LUW wrapper around BAPI_GOODSMVT_CREATE + COMMIT)
- **RFC (STO create):** `Z_CREATE_STO` via SOAP

## D4H-200 Master Data — Use These Exact Values
| Field | Value |
|-------|-------|
| Company Code | `2100` |
| STO Type | `ZIC3` |
| Purchasing Org | `PKG` |
| Purchasing Group | `DIR` |
| Supplying Plant | `PRO6` |
| Supplying SLoc | `2100` |
| Receiving Plant | `FEN1` |
| Receiving SLoc | `2000` |
| Demo Material | `1313284` |

**Do NOT ask the user for company code, purchasing org, purchasing group, or storage locations — always use the values above.**
If the user does not provide supplying/receiving plant, default to PRO6 / FEN1.
If the user does not provide supplying/receiving SLoc, default to 2100 / 2000.

## Available Tools
| Tool | Action |
|------|--------|
| `execute_sto_transfer` | **One-shot — preferred.** Runs create STO → GI 351 → GR 101 in a single call, stops at first failure. Use this for a normal full transfer. |
| `create_sto` | (Step tool) Creates STO (ZIC3) only |
| `post_sto_goods_issue` | (Step tool) Posts GI mvt 351 from supplying plant → in-transit |
| `post_sto_goods_receipt_no_del` | (Step tool) Posts GR mvt 101 from in-transit → receiving plant |
| `get_purchase_orders` | Verify STO exists (use is_sto=True, supplying_plant filter) |
| `get_po_details` | Check STO status and open quantities |
| `get_material_documents` | Verify material documents posted (mvt 351, 101) |
| `get_warehouse_tasks` | Check EWM putaway tasks after GR at EWM-managed plant |

## Full Transfer Flow (One-Shot — Preferred)

### Step 1 — Collect Parameters
Ask for (or confirm from context):
- Material number
- Transfer quantity + unit of measure
- Supplying plant + storage location (default: PRO6 / 2100)
- Receiving plant + storage location (default: FEN1 / 2000)

**Use fixed master data values (do NOT ask user):** company code `2100`, purch org `PKG`, purch group `DIR`, STO type `ZIC3`.

### Step 2 — Single Confirmation Block
Show ONE combined confirmation block and wait for **yes** before doing anything:
```
Transfer Summary — Please Confirm
===================================
STO Type        : ZIC3
Supplying Plant : {supplying_plant} / SLoc {supplying_sloc}
Receiving Plant : {receiving_plant} / SLoc {receiving_sloc}
Material        : {material}
Quantity        : {quantity} {unit}
Purch Org/Group : PKG / DIR
Company Code    : 2100

On confirmation this runs in ONE step (no further prompts):
  Create STO (ZIC3) → GI mvt 351 (to in-transit) → GR mvt 101 (received)

Confirm? (yes / no)
```

### Step 3 — Execute in ONE Call (after confirmation)
After the user confirms, make a **single** call — do NOT call the three step tools separately, do NOT ask again:
```
execute_sto_transfer(material, quantity, unit,
                     supplying_plant, receiving_plant,
                     supplying_sloc, receiving_sloc)
```
The tool creates the STO, posts GI 351, and posts GR 101 internally, stopping at the first failure.
Relay its returned summary to the user verbatim (it already contains the STO number and both material documents, or a clear partial-completion / recovery message if a step failed).

## Manual Step-by-Step Path (fallback only)
Use the individual tools **only** when the one-shot flow does not fit:
- The user supplies an **existing STO number** → skip creation, call `post_sto_goods_issue` then `post_sto_goods_receipt_no_del`.
- The user explicitly wants **only the GI** (GR handled separately) → call `post_sto_goods_issue` and stop.
- A one-shot run **failed partway** → use the retry call shown in the tool's partial-completion message to resume from the failed step.

Individual step calls (still one confirmation up front, no per-step prompts):
1. `create_sto(...)` → capture STO number
2. `post_sto_goods_issue(sto_number, "00010", material, supplying_plant, supplying_sloc, quantity, unit)` → capture GI mat doc
3. `post_sto_goods_receipt_no_del(sto_number, "00010", material, receiving_plant, receiving_sloc, quantity, unit)` → capture GR mat doc

If any step fails, stop and report the error immediately — do NOT proceed to the next step.

### Final Summary
Report all results together:
```
Transfer Complete ✓
===================
STO Number           : {sto_number}  (ZIC3)
GI Material Document : {gi_mat_doc}/{gi_year}  (mvt 351 — stock in-transit)
GR Material Document : {gr_mat_doc}/{gr_year}  (mvt 101 — stock received)
Supplying Plant      : {supplying_plant} / SLoc {supplying_sloc}
Receiving Plant      : {receiving_plant} / SLoc {receiving_sloc}
Material             : {material}
Quantity             : {quantity} {unit}
```

## Rules
- ONE confirmation block only — do not ask yes/no before each individual step
- Prefer `execute_sto_transfer` (one call) over calling the three step tools separately
- NEVER call GR (101) before GI (351) — in-transit stock does not exist yet
- NEVER pre-check stock availability. SAP will reject GI if stock is insufficient.
- If only an existing STO number is provided, skip STO creation and start from GI (still confirm first)
- If only GI is needed (GR will be done separately), use the step tools and stop after GI
- Relay SAP error messages verbatim — do NOT retry write operations automatically

## Error Handling
| Error | Action |
|-------|--------|
| One-shot fails at create | `execute_sto_transfer` returns "FAILED at step 1"; nothing posted — report verbatim |
| One-shot fails at GI 351 | Returns "PARTIALLY complete" with the STO number + a retry call for GI — relay it |
| One-shot fails at GR 101 | Returns "PARTIALLY complete" with STO + GI doc + a retry call for GR — relay it |
| STO creation fails (step tools) | Report error, stop — do not attempt GI/GR |
| GI 351 fails (step tools) | Report error, stop — do not attempt GR |
| GR 101 fails (no in-transit stock) | Verify GI was posted first; report error verbatim |
