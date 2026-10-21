---
name: ewm-stock-skill
description: Guides the agent to query EWM bin-level available stock and physical stock totals using OData V4 APIs API_WHSE_AVAILABLESTOCK and API_WHSE_PHYSSTOCKPROD on D4H-200.
---

# EWM Stock Skill

## System Context
- **System:** D4H-200 — `10.254.2.59:44300`, client 200
- **APIs (OData V4):**
  - `API_WHSE_AVAILABLESTOCK` — bin-level available stock
    - Root: `/sap/opu/odata4/sap/api_whse_availablestock/srvd_a2x/sap/api_whse_availablestock/0001`
    - Entity: `WarehouseAvailableStock`
  - `API_WHSE_PHYSSTOCKPROD` — physical stock totals per product
    - Root: `/sap/opu/odata4/sap/api_whse_physstockprod/srvd_a2x/sap/api_whse_physstockprod/0001`
    - Entity: `WarehousePhysicalStockProducts`

## Real Values
- EWM Warehouse: `PBAR`, Plant: `BAR1`
- Products: `1010028`, `1010114`, `1111011`, `1111039`, `1111044`, `1111104`
- Sample bins: `H13C2`, `B20G1D`, `LDC1`, `C2B1`, `H13A2`, `GI-ZONE`, `GR-DOCK`
- Storage types: `1000`, `2000`, `3000`, `4000`, `9010`, `9020`, `9040`, `CL01`, `FLR`, `P100`

## Available Tools
- `get_ewm_available_stock(ewm_warehouse, product, storage_bin, stock_type, top)` — bin-level stock
- `get_ewm_physical_stock(ewm_warehouse, product, top)` — physical totals

## EWM Stock Type Codes
| Code | Meaning |
|------|---------|
| F | Unrestricted |
| Q | Quality Inspection |
| S | Blocked |
| T | In Transfer |
| R | Returns |
| W | Work in Process |

## Query Flow
1. For bin-level detail: `get_ewm_available_stock(ewm_warehouse='PBAR', product='1111044')`
2. For totals summary: `get_ewm_physical_stock(ewm_warehouse='PBAR', product='1010028')`
3. For blocked/QI stock only: add `stock_type='S'` or `stock_type='Q'`

## Important: MM vs EWM Stock
- `get_material_stock` / `get_stock_overview` = MM (plant-level account model)
- `get_ewm_available_stock` / `get_ewm_physical_stock` = EWM (bin-level warehouse model)
- Both can show the same product — use EWM tools for bin/location detail, MM tools for financial stock

## Error Handling
- If no rows returned, product may have zero stock or service binding inactive — report verbatim
- Do NOT fabricate quantities
