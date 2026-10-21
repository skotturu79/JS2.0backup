---
name: storage-bin-skill
description: Guides the agent to query EWM Storage Bin master data and Fixed Bin Assignments using OData V4 APIs API_WHSE_STORAGE_BIN_2 and API_WHSE_FIXBIN_ASSGNMNT on D4H-200.
---

# Storage Bin & Fixed Bin Skill

## System Context
- **System:** D4H-200 — `10.254.2.59:44300`, client 200
- **APIs (OData V4):**
  - `API_WHSE_STORAGE_BIN_2` — Storage Bin master
    - Root: `/sap/opu/odata4/sap/api_whse_storage_bin_2/srvd_a2x/sap/api_warehouse_storage_bin_2/0001`
    - Entity: `WarehouseStorageBin`
  - `API_WHSE_FIXBIN_ASSGNMNT` — Fixed Bin Assignments
    - Root: `/sap/opu/odata4/sap/api_whse_fixbin_assgnmnt/srvd_a2x/sap/api_whse_fixbin_assgnmnt/0001`
    - Entity: `WarehouseFixedBinAssignment`

## Real Values
- EWM Warehouse: `PBAR`
- Storage types: `1000`, `2000`, `3000`, `4000`, `8040`, `9000`, `9010`, `9015`, `9020`, `9030`, `9040`, `CL01`, `FLR`, `P100`, `REJE`, `T001`, `T002`, `TRLR`, `Y820`, `Y860`
- Sample bins: `B20G1D`, `B20G2D`, `H13A2`, `H13C2`, `LDC1`, `LDC4`, `C2B1`, `GR-DOCK`, `GI-ZONE`, `CLARIFICATION`
- Note: No fixed bin assignments configured in PBAR as of Aug 2026

## Available Tools
- `get_storage_bins(ewm_warehouse, storage_section, bin_type, aisle, top)` — bin master data
- `get_fixed_bin_assignments(ewm_warehouse, product, storage_bin, top)` — product-bin assignments

## Query Flow
- To find bins in a storage type: `get_storage_bins(ewm_warehouse='PBAR', storage_type='3000')`
- To find put-away bin for a product: `get_fixed_bin_assignments(ewm_warehouse='PBAR', product='1111044')`
- To find empty bins: `get_storage_bins(ewm_warehouse='PBAR', empty_only=True)`

## Use Cases
- Put-away guidance: find fixed bin for product before confirming warehouse task
- Replenishment planning: check MinimumQuantity and ReplenishmentQuantity from fixed bin assignments
- Capacity planning: check MaximumWeight on bins in a section

## Error Handling
- If no rows returned, bin or assignment may not exist — report verbatim, do not fabricate
