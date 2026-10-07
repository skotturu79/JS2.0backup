---
name: warehouse-task-confirm-skill
description: Guides the agent to confirm EWM Warehouse Tasks via SOAP RFC on D4H-200. ALWAYS requires explicit yes/no confirmation before calling the tool.
---

# Warehouse Task Confirmation Skill

## System Context
- **System:** D4H-200 — `10.254.2.59:44300`, client 200
- **Method:** SOAP RFC `/SCWM/TO_CONFIRM` (NOT OData V4 bound action — ICF node not activated on D4H)
- **Endpoint:** `/sap/bc/soap/rfc`
- **FM encoded as:** `_-SCWM_-TO_CONFIRM` in SOAP envelope
- **EWM Warehouse:** `PBAR`, Plant: `BAR1`

## Available Tools
- `confirm_warehouse_task_exact(ewm_warehouse, warehouse_order, warehouse_task, warehouse_task_item, actual_quantity, destination_bin)` — exact confirmation
- `confirm_warehouse_task(ewm_warehouse, warehouse_order, warehouse_task, warehouse_task_item, actual_quantity, destination_bin)` — partial/override confirmation

## Confirmation Flow (MANDATORY)
1. Call `get_warehouse_task_detail` to retrieve and display task details
2. Show this confirmation block:
```
Task Confirmation Summary
=========================
Warehouse      : {ewm_warehouse}
Order          : {warehouse_order}
Task           : {warehouse_task} / Item {warehouse_task_item}
Product        : {product}
Source Bin     : {source_bin}
Destination    : {destination_bin or planned bin}
Target Qty     : {target_qty} {unit}
Actual Qty     : {actual_qty}
Action         : Confirm Warehouse Task (Exact / Partial)

Confirm? (yes / no)
```
3. Only call the tool after the user replies **yes**

## Rules
- NEVER call confirm_warehouse_task or confirm_warehouse_task_exact without user confirmation
- If actual = target → prefer `confirm_warehouse_task_exact`
- If actual ≠ target or bin override needed → use `confirm_warehouse_task`

## Error Handling
- Surface RFC/OData errors verbatim
- If 400 error on ConfirmWarehouseTaskExact with qty mismatch, retry with ConfirmWarehouseTask
