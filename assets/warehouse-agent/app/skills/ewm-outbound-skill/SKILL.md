---
name: ewm-outbound-skill
description: Guides the agent to query EWM Outbound Delivery Orders and their line items using OData V4 API_WAREHOUSE_ODO_2 on D4H-200.
---

# EWM Outbound Delivery Skill

## System Context
- **System:** D4H-200 — `10.254.2.59:44300`, client 200
- **API:** `API_WAREHOUSE_ODO_2` (OData V4)
- **Service root:** `/sap/opu/odata4/sap/api_warehouse_odo_2/srvd_a2x/sap/api_whse_outb_delivery_order_2/0001`
- **Entity sets:** `WhseOutboundDeliveryOrderHead`, `WhseOutboundDeliveryOrderItem`
- ⚠️ Always use explicit `$select` — `EWMOutbDlvOrdAdhocLoadgIsActv` column missing from DB, causes HTTP 500 without it

## Real Values
- EWM Warehouse: `PBAR`, Plant: `BAR1`
- Products: `1010005`, `1010010`, `1010028`, `1111011`, `1111044`
- No open ODOs in PBAR as of Aug 2026

## Available Tools
- `get_ewm_outbound_deliveries(ewm_warehouse, status, ship_to_party, top)` — list ODO headers
- `get_ewm_outbound_delivery_items(ewm_warehouse, outbound_delivery_order)` — ODO line items

## Status Codes
| Code | Meaning |
|------|---------|
| A | Not Started |
| B | In Process |
| C | Completed |

## Query Flow
1. `get_ewm_outbound_deliveries(ewm_warehouse='PBAR', status='A')` — open ODOs
2. `get_ewm_outbound_delivery_items(ewm_warehouse='PBAR', outbound_delivery_order='<odo>')` — items

## Important
- These are EWM-layer Outbound Delivery **Orders** (ODO) — different from SD outbound deliveries
- Status reflects warehouse activity, not GI status
- For GI status and SD-layer deliveries, use `get_delivery_doc_flow` or SD APIs

## Error Handling
- If service inactive, report 404 verbatim — do not fabricate
