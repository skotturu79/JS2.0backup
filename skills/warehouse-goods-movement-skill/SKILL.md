---
name: warehouse-goods-movement-skill
description: Guides the agent to query goods movement history and post goods receipts (mvt 101) against inbound deliveries on SAP S/4HANA D4H-200. Field name is Delivery (not DeliveryDocument) in A_MaterialDocumentItem.
---

# Warehouse Goods Movement Skill

## System Context
- **System:** D4H-200 — `10.254.2.59:44300`, client 200
- **Active API:** `API_MATERIAL_DOCUMENT_SRV`
- **Key entity:** `A_MaterialDocumentItem`
- **Important field name:** `Delivery` (NOT `DeliveryDocument`) for delivery reference in items

## Real Values
- Plant: `BAR1`, EWM Warehouse: `PBAR`
- Materials: `1010028`, `1010114`, `1111011`, `1111039`, `1111044`, `1111104`
- BAR1 is EWM-managed — movement types 101/601 are the primary GR/GI types

## Available Tools
- `get_material_documents(material, plant, batch, movement_type, top)` — history
- `post_goods_receipt(delivery_document, plant)` — mvt 101 (requires user confirmation)

## Movement Type Reference
| Code | Description |
|------|-------------|
| 101 | GR against Purchase Order |
| 201 | GI to Cost Center |
| 261 | GI to Production Order |
| 321 | Transfer QI → Unrestricted |
| 501 | Receipt without Reference |
| 551 | Scrapping |
| 601 | GI for Delivery (Outbound) |
| 641 | Stock Transfer (one-step) |

## GR Posting Flow
1. Verify delivery via `get_delivery_items`
2. Show confirmation block — NEVER post without explicit user approval:
```
Goods Receipt Summary
=====================
Inbound Delivery : {delivery}
Plant            : {plant}
Action           : Post GR (Movement Type 101)
Confirm? (yes / no)
```
3. Call `post_goods_receipt(delivery_document, plant)` after confirmation

## Result Summary Format
```
Result Summary
==============
Material Document : {mat_doc}/{year}
Delivery          : {delivery}
Plant             : {plant}
Movement Type     : 101 — Goods Receipt against PO
```

## Error Handling
- NEVER post GR without explicit user confirmation
- Auth error: surface verbatim, do NOT retry
