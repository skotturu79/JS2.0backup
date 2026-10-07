---
name: cross-warehouse-stock-skill
description: Guides the agent to query EWM physical stock across all 34 warehouses using get_cross_warehouse_stock — tabular format grouped by warehouse showing Unrestricted/Quality/Blocked/InTransfer totals.
---

# Cross-Warehouse Stock Skill

## System Context
- **System:** D4H-200 — client 200
- **API (OData V4):** `API_WHSE_PHYSSTOCKPROD`
  - Path: `/sap/opu/odata4/sap/api_whse_physstockprod/srvd_a2x/sap/api_whse_physstockprod/0001`
  - Entity: `WarehousePhysicalStockProducts`

## EWM Warehouses on D4H-200 (34 total)
`2910` `BAR1` `BAR2` `BBG1` `CRE1` `DEMO` `FEN1` `LAN1` `LEB1` `LOC1`
`MBBG` `MLEB` `MSTR` `MWIL` `ORM1` `ORM2` `PAR1` `PBAR` `PCRE` `PFEN`
`PLA3` `PLOC` `POR1` `POR2` `PWOO` `SEC2` `STR1` `TEA1` `WFEN` `WIL2`
`WOO1` `Z001` `Z002` `Z003`

## Available Tool
| Tool | Purpose |
|---|---|
| `get_cross_warehouse_stock` | Stock across all EWM warehouses — tabular grouped summary |

## Named Warehouse Groups
| Group | Warehouses |
|---|---|
| `CASA` | PBAR, POR2, PWOO, PFEN, PLA3, WFEN |

Use `group='LIST'` to list all defined groups at runtime.

## Tool Parameters
| Parameter | Description |
|---|---|
| `group` | Named group: `CASA` — resolves to warehouse list. Use `LIST` to see all groups. |
| `product` | Product/material number (optional but recommended) |
| `warehouses` | Comma-separated warehouse codes to limit scope (e.g. `PBAR,MSTR`) |
| `stock_type` | F=Unrestricted, Q=Quality, S=Blocked, T=InTransfer |
| `group_by_warehouse` | true=summary by warehouse (default), false=individual lines |
| `top` | Max records (default 200, max 500) |

## Output Format

**With product specified (recommended):**
```
Product: 1111044
Warehouse   Unrestricted    Quality     Blocked    InTransfer  Unit
------------------------------------------------------------------
PBAR             120.000      0.000       0.000        0.000   EA
MSTR              50.000      5.000       0.000        2.000   EA
...
TOTAL            170.000      5.000       0.000        2.000   EA
```

**Without product (all products):**
```
Warehouse PBAR  (total lines: 15, total qty: 850):
    1010028                   Unres:120.000 EA
    1111044                   Unres:320.000 | QI:5.000 EA
...
```

## Query Flow

### Find all warehouses that stock a specific product
1. `get_cross_warehouse_stock(product='1111044')`

### Query CASA warehouses only
1. `get_cross_warehouse_stock(group='CASA', product='1111044')`

### List all defined warehouse groups
1. `get_cross_warehouse_stock(group='LIST')`

### Compare stock levels across selected warehouses
1. `get_cross_warehouse_stock(product='1010028', warehouses='PBAR,MSTR,STR1')`

### See only unrestricted stock across all warehouses for a product
1. `get_cross_warehouse_stock(product='1111044', stock_type='F')`

### Full stock overview for a specific warehouse
1. `get_cross_warehouse_stock(warehouses='PBAR', top=200)`

## Sample Prompts
- "Show stock for product 1111044 in CASA warehouses"
- "List all CASA warehouses"
- "Show unrestricted stock for 1010028 in CASA warehouses"
- "Give me a stock summary for all CASA warehouses"
- "Which CASA warehouse has the most stock for product 1111044?"
- "Show stock for product 1111044 across all warehouses"
- "Where is material 1010028 stocked across all EWM warehouses?"
- "Compare stock for 1111044 in warehouses PBAR and MSTR"
- "Show all unrestricted stock for product 1111044 across all warehouses"
- "Give me the full stock overview for warehouse PBAR"
- "Which warehouses have stock for product 1111039?"
- "Show quality inspection stock for 1111044 across all warehouses"
- "Show stock across all warehouses for material 5002731-01-00"

## Error Handling
- No results: product may have zero stock or be unknown in EWM
- Large result sets: add product filter or use warehouses parameter to narrow scope
- Do NOT fabricate quantities
