---
name: warehouse-inbound-delivery-skill
description: Guides the agent to list, inspect, and track inbound deliveries on SAP S/4HANA D4H-200. Plant filter must go via items (ReceivingPlant is blank on headers). Covers detail, items, and PO→Delivery→GR document flow.
---

# Warehouse Inbound Delivery Skill

## System Context
- **System:** D4H-200 — `10.254.2.59:44300`, client 200
- **Active API:** `API_INBOUND_DELIVERY_SRV;v=0002`
- **Important:** `ReceivingPlant` on `A_InbDeliveryHeader` is always blank on D4H — plant lives at item level (`A_InbDeliveryItem.Plant`). When filtering by plant, the tool queries items first, then fetches headers.

## Entity Sets
- `A_InbDeliveryHeader` — DeliveryDocument, Supplier, ShippingPoint, OverallGoodsMovementStatus, DeliveryDate
- `A_InbDeliveryItem` — Plant, Material, Batch, Qty, GoodsMovementStatus
- `A_InbDeliveryDocFlow` — preceding PO, subsequent GR document

## Real Values
- Plant: `BAR1`, EWM Warehouse: `PBAR`
- Materials: `1010005`, `1010010`, `1010012`, `1010028`, `1111011`, `1111044`
- No open inbound deliveries at BAR1 as of Aug 2026 (use without plant filter to see all)

## Available Tools
- `get_inbound_deliveries(plant, supplier, top)` — plant filter via items; no plant = header list
- `get_inbound_delivery_detail(delivery_document)` — full header
- `get_delivery_items(delivery_document)` — line items with material, batch, qty, GR status
- `get_delivery_doc_flow(delivery_document)` — PO → delivery → GR chain

## GR Status Codes
| Code | Meaning |
|------|---------|
| A | Not started |
| B | Partial |
| C | Complete |

## Query Flow
1. `get_inbound_deliveries(plant)` — list deliveries
2. `get_delivery_items(delivery)` — see materials and quantities
3. `get_delivery_doc_flow(delivery)` — trace PO and GR

## Output Format
```
Inbound Deliveries for Plant BAR1 (top 10):
  Delivery: 180001025  Type: EL  Supplier: -  ShipPt: -  GR Status: Complete  Date: ...

Items for Delivery 180001025:
  Item: 000010  Material: 1010028  Batch: -  Plant: BAR1  SLoc: -  Qty: 100 KG  GR: Complete

Document Flow for Delivery 180001025:
  Preceding: 4500001267 (Cat: V) → Subsequent: 5000001521 (Cat: WA)
```

## Error Handling
- If no deliveries found, inform user
- Auth error: surface verbatim, do NOT retry
