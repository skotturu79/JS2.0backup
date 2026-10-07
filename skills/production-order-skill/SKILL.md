---
name: production-order-skill
description: Guides the agent to query SAP PP production orders — header, status codes, BOM components, routing operations — using OData V2 API_PRODUCTION_ORDER_2_SRV on D4H-200.
---

# Production Order Skill

## System Context
- **System:** D4H-200 — client 200, Plant: `BAR1`
- **API (OData V2):** `API_PRODUCTION_ORDER_2_SRV`
  - Path: `/sap/opu/odata/sap/API_PRODUCTION_ORDER_2_SRV`

## Real Values (D4H-200 / BAR1)
- Plant: `BAR1`, Order type: `YBM1`
- Sample orders: `1000000`, `1001176`, `1001177`, `1001182`, `1001214`, `1001294`
- Sample materials: `5002939-00-00`, `5002732-01-00`, `5002731-01-00`, `5007822-00-00`, `5100669-00-01`

## Available Tools
| Tool | Entity Set | Purpose |
|---|---|---|
| `get_production_orders_v2` | `A_ProductionOrder_2` | List/search orders; single order detail |
| `get_production_order_status_v2` | `A_ProductionOrderStatus_2` | All system + user status codes |
| `get_production_order_components_v2` | `A_ProductionOrderComponent_2` | BOM components, open qty, shortages |
| `get_production_order_operations_v2` | `A_ProductionOrderOperation_2` | Routing operations, work center, yield |

## Status Filter Values (for `get_production_orders_v2`)
| Filter | Meaning |
|---|---|
| `REL` | Released — ready for production |
| `CNF` | Confirmed — fully confirmed |
| `TECO` | Technically Completed |
| `OPEN` | Not closed or TECO (active orders) |

## System Status Codes
| Code | Meaning |
|---|---|
| CRTD | Created |
| REL | Released |
| PCNF | Partially Confirmed |
| CNF | Confirmed |
| DLV | Delivered |
| TECO | Technically Completed |
| CLSD | Closed |
| DLFL | Deletion Flag |

## Query Flow

### List orders for a plant
1. `get_production_orders_v2(plant='BAR1', status_filter='REL', top=20)`

### Single order full detail
1. `get_production_orders_v2(production_order='1001176')` — header
2. `get_production_order_status_v2(production_order='1001176')` — all status codes
3. `get_production_order_components_v2(production_order='1001176')` — components
4. `get_production_order_operations_v2(production_order='1001176')` — operations

### Check component availability / shortages
1. `get_production_order_components_v2(production_order='1001182')`
   - Open qty = RequiredQuantity − WithdrawnQuantity
   - ConfirmedAvailableQuantity shows EWM-confirmed stock

## Sample Prompts

**Order List & Search**
- "List released production orders for plant BAR1"
- "Show open production orders for plant BAR1"
- "List production orders for material 5002731-01-00 at BAR1"
- "Show all technically completed orders at BAR1"

**Single Order Detail**
- "Show details for production order 1001176"
- "What is the status of production order 1001182?"
- "Give me a full picture of production order 1001176 — status, components, and operations"

**Status**
- "Get all status codes for production order 1001176"
- "Is production order 1001294 released or confirmed?"
- "Which production orders at BAR1 have user status ZCAN (Cancelled)?"

**Components**
- "Show components for production order 1001176"
- "What materials are required for production order 1001182?"
- "Are there any shortages for production order 1001176?"
- "Which components have not been fully issued for order 1001182?"

**Operations**
- "Show operations for production order 1001176"
- "What work centers are used in production order 1001182?"
- "Which operations are confirmed for production order 1001176?"

## Error Handling
- If `ManufacturingOrderStatus` appears in an error — it is NOT a field in `A_ProductionOrder_2`; use `get_production_order_status_v2` instead
- Status flags on `A_ProductionOrder_2` are boolean fields: `OrderIsReleased`, `OrderIsConfirmed`, `OrderIsTechnicallyCompleted`, `OrderIsClosed`
- Do NOT fabricate order numbers or quantities
