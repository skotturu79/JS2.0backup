---
name: warehouse-stock-skill
description: Guides the agent to query current warehouse stock levels by material, plant, storage location, and batch on SAP S/4HANA D4H-200. Uses A_MatlStkInAcctMod (not A_MaterialStock — Plant field only exists on the former).
---

# Warehouse Stock Skill

## System Context
- **System:** D4H-200 — `10.254.2.59:44300`, client 200
- **Active API:** `API_MATERIAL_STOCK_SRV`
- **Key entity:** `A_MatlStkInAcctMod` — has Material, Plant, StorageLocation, Batch, InventoryStockType, MatlWrhsStkQtyInMatlBaseUnit
- **Do NOT use** `A_MaterialStock` for plant-filtered queries — Plant is not a filterable field there
- ⚠️ BAR1 is EWM-managed — `API_MATERIAL_STOCK_SRV` returns HTTP 500 for BAR1. Use EWM stock tools instead.

## Real Values
- Plant: `BAR1` (EWM-managed — MM stock API not applicable, use EWM tools)
- EWM Warehouse: `PBAR`
- Materials: `1010005`, `1010010`, `1010012`, `1010028`, `1010114`, `1111011`, `1111039`, `1111044`, `1111104`

## Available Tools
- `get_material_stock` — stock per batch/SLoc/type; plant optional (blank = all plants)
- `get_stock_overview` — non-zero quantities only, labelled stock types

## Stock Type Codes
| Code | Label |
|------|-------|
| 01 | Unrestricted |
| 02 | Quality Inspection |
| 03 | Blocked |
| 06 | In Transit |
| 07 | Restricted Use |

## Query Flow
1. For EWM-managed plant BAR1 — use EWM tools: `get_ewm_physical_stock(ewm_warehouse='PBAR', product='1111044')`
2. For MM stock (non-EWM plants): `get_material_stock(material, plant)` or `get_stock_overview(material, plant)`

## Output Format
```
Stock for {material} / Plant {plant}:
  Plant: BAR1  SLoc: -  Batch: -  Qty: 108.84 KG  StockType: Unrestricted
```

## Error Handling
- If no stock found, inform user — do not fabricate quantities
- Auth error: surface verbatim, do NOT retry
