---
name: warehouse-order-skill
description: Guides the agent to query EWM Warehouse Orders and Tasks on D4H-200 using OData V4 API_WAREHOUSE_ORDER_TASK_2. Entity set paths are WarehouseOrder and WarehouseTask under the V4 service root.
---

# Warehouse Order & Task Skill

## System Context
- **System:** D4H-200 — `10.254.2.59:44300`, client 200
- **API:** `API_WAREHOUSE_ORDER_TASK_2` (OData V4)
- **Service root:** `/sap/opu/odata4/sap/api_warehouse_order_task_2/srvd_a2x/sap/api_warehouse_order_task_2/0001`
- **Entity sets:** `WarehouseOrder`, `WarehouseTask`
- **V4 response envelope:** `{"value": [...]}` — NOT `{"d": {"results": [...]}}`

## Real Values
- EWM Warehouse: `PBAR`, Plant: `BAR1`
- Recent orders: `3002920`–`3002924` (all Confirmed as of Aug 2026)
- Products: `1010028`, `1010114`, `1111011`, `1111039`, `1111044`
- Queues: `INBOUND`, `INTERNAL`, `PICOUNT`

## Available Tools
- `get_warehouse_orders(ewm_warehouse, status, activity_area, top)` — list orders
- `get_warehouse_tasks(ewm_warehouse, warehouse_order, product, executing_resource, status, top)` — list tasks
- `get_warehouse_task_detail(ewm_warehouse, warehouse_order, warehouse_task, warehouse_task_item)` — single task

## Status Codes
| Code | Orders | Tasks |
|------|--------|-------|
| A | Open | Open |
| B | In Progress | In Progress |
| C | Confirmed | Confirmed |
| D | - | Cancelled |

## Query Flow
1. `get_warehouse_orders(ewm_warehouse='PBAR', status='A')` — open orders
2. `get_warehouse_tasks(ewm_warehouse='PBAR', warehouse_order='<order>')` — tasks for order
3. `get_warehouse_task_detail(...)` — full detail before confirmation

## Output Format
```
Warehouse Orders — WH PBAR (top 5):
  Order: 3002924  Status: Confirmed  Area: 9020  Queue: INTERNAL  Resource: -  ProcType: 9999  Created: 2026-08-17 13:48:05

Warehouse Tasks — WH PBAR (top 5):
  Task: 0000001234  Order: 3002924  Status: Open  Product: 1111044
  From: GR-DOCK  To: H13A2  TgtQty: 250 KG  ActQty: 0  Resource: -
```

## Error Handling
- If service returns 404/not-found, service binding for API_WAREHOUSE_ORDER_TASK_2 may not be active — report verbatim
- Do NOT fabricate task or order numbers
