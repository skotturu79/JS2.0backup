---
name: warehouse-skills-overview
description: Quick reference for all warehouse agent skills and sample prompts. Use this when the user asks what the agent can do, or wants to see available skills and example questions.
---

# Warehouse Agent — Skills & Sample Prompts

**System:** D4H-200 (10.254.2.59:44300) | Client 200 | EWM Warehouse: PBAR | Plant: BAR1

---

## 1. MM Stock Query (`warehouse-stock-skill`)
Check warehouse stock levels by material, plant, storage location, batch.
```
- Show stock for material 1111044 in plant BAR1
- What is the stock overview for 1010028?
- List all batches for material 1111011 in plant BAR1
```

## 2. EWM Stock Query (`ewm-stock-skill`)
Bin-level available and physical stock inside EWM warehouse PBAR.
```
- Show available stock for product 1111044 in storage type 3000 in warehouse PBAR
- List all unrestricted stock in warehouse PBAR
- What is the physical stock for 1010028 in warehouse PBAR?
- Show stock in bin H13A2 in warehouse PBAR
```

## 3. Cross-Warehouse Stock (`cross-warehouse-stock-skill`)
Query EWM physical stock across ALL 34 warehouses in one call — tabular summary.
```
- Show stock for product 1111044 across all warehouses
- Where is material 1010028 stocked across all EWM warehouses?
- Compare stock for 1111044 in warehouses PBAR and MSTR
- Show all unrestricted stock for product 1111044 across all warehouses
- Give me the full stock overview for warehouse PBAR
- Which warehouses have stock for product 1111039?
- Show quality inspection stock for 1111044 across all warehouses
```

## 4. Warehouse Orders & Tasks (`warehouse-order-skill`)
EWM Warehouse Orders and Tasks — query, filter, inspect.
```
- List open warehouse orders in warehouse PBAR
- Show warehouse tasks for order 3002924
- Get detail for warehouse task in order 3002924
- What tasks are in queue INBOUND for warehouse PBAR?
```

## 5. Warehouse Task Confirmation (`warehouse-task-confirm-skill`)
Confirm EWM warehouse tasks after physical execution (requires yes/no approval).
```
- Confirm warehouse task in order 3002924 with exact quantity
- Confirm task with actual quantity to bin H13A2
```

## 6. Inbound Deliveries (`warehouse-inbound-delivery-skill`)
List and inspect inbound deliveries, items, and document flow.
```
- List inbound deliveries for plant BAR1
- Show all open inbound deliveries
- What is the document flow for a delivery?
- Show items for an inbound delivery
```

## 7. EWM Outbound Deliveries (`ewm-outbound-skill`)
EWM Outbound Delivery Orders from the warehouse perspective.
```
- List outbound deliveries in warehouse PBAR
- Show open ODOs in PBAR
- List outbound delivery items for warehouse PBAR
```

## 8. Storage Bins (`storage-bin-skill`)
Storage bin master data and fixed bin assignments.
```
- Show bin H13A2 in warehouse PBAR
- List all bins in storage type 3000 in warehouse PBAR
- Show empty bins in storage type 9010 in PBAR
- What are the storage types in warehouse PBAR?
```

## 9. Goods Movement & GR Posting (`warehouse-goods-movement-skill`)
Material document history — GR, GI, transfers, scrapping — plus posting goods receipts against
inbound deliveries (movement type 101, requires confirmation).
```
- Show goods movements for material 1111044 in plant BAR1
- List goods receipts (mvt 101) for plant BAR1
- Show all GI movements (mvt 601) for plant BAR1
- Post goods receipt for inbound delivery at plant BAR1
```

## 10. EWM Physical Inventory (`ewm-physical-inventory-skill`)
Physical inventory documents and count items in EWM warehouse PBAR.
```
- List active physical inventory documents in warehouse PBAR
- Show physical inventory docs for storage type 3000 in warehouse PBAR
- Get count items for physical inventory document 400024
- Are there any open inventory documents for product 1999904?
```

## 11. Production Orders (`production-order-skill`)
View production orders, status, BOM components, and routing operations via OData V2.
```
- List released production orders for plant BAR1
- Show open production orders for plant BAR1
- List production orders for material 5002731-01-00 at BAR1
- Show details for production order 1001176
- What is the status of production order 1001182?
- Get all status codes for production order 1001176
- Is production order 1001294 released or confirmed?
- Show components for production order 1001176
- What materials are required for production order 1001182?
- Are there any shortages for production order 1001176?
- Show operations for production order 1001176
- What work centers are used in production order 1001182?
- Give me a full picture of production order 1001176 — status, components, and operations
```

## 12. Stock Transfer 3PL → FEN1 Via IM (`sto-nodel-skill`)
Transfer non-batch material from the 3PL plant (PRO6) to receiving plant FEN1 via Inventory
Management — create STO (ZIC3) → GI mvt 351 → GR mvt 101. No inbound delivery. Runs the whole
flow in ONE step (`execute_sto_transfer`) after a single confirmation — no per-step prompts.
```
- Transfer 1 KG of 1313284 from 3PL PRO6 to FEN1
- Move material 1313284 from PRO6/2100 to FEN1/2000, 1 KG
- Do a stock transfer from 3PL to FEN1 via IM for 1313284 in one step
- Post GI 351 then GR 101 for STO 4800015101
```

## 13. EWM Inbound Delivery Goods Receipt (`ewm-inbound-gr-skill`)
Post a goods receipt against an EWM inbound delivery — full (all open items) or partial (specific
items/quantities) via the standard Warehouse Inbound Delivery A2X OData V4 API, or at the **handling-unit
level** (post GR for one or more specific HUs) via the custom `Z_EWM_GR_HU_POST` FM. EWM-owned
delivery-based GR, distinct from the IM/STO route (mvt 101). Requires one confirmation.
```
- Read EWM inbound delivery 180000123 and its items
- Post full goods receipt for EWM inbound delivery 180000123
- Post partial GR for delivery 180000123: item 10 = 5 KG
- Post GR for handling unit HU0001 on delivery 180000123
- Post GR for handling units HU0001 and HU0002 on delivery 180000123
```

---

## Real Materials (WH PBAR / Plant BAR1)
`1010005` `1010010` `1010012` `1010016` `1010017` `1010019` `1010020` `1010028` `1010114` `1111010` `1111011` `1111039` `1111044` `1111104`

## Production Order Materials (Plant BAR1)
`5002939-00-00` `5002732-01-00` `5002731-01-00` `5007822-00-00` `5100669-00-01` `5100841-00-00`

## Sample Production Orders (Plant BAR1)
`1000000` `1001176` `1001177` `1001182` `1001214` `1001294`

## Storage Types (EWM WH PBAR)
`1000` `2000` `3000` `4000` `8040` `9000` `9010` `9015` `9020` `9030` `9040` `CL01` `FLR` `P100` `REJE` `T001` `T002` `TRLR` `Y820` `Y860`

## Sample Bins
`H13A2` `H13C2` `B20G1D` `C2B1` `LDC1` `LDC4` `GR-DOCK` `GI-ZONE` `CLARIFICATION` `FLRF` `BTA14` `J1C2` `H11B2`

## Active Physical Inventory Docs
`400024` (2026, bin J1C2, ST 3000) · `400026` (2026, bin H11B2, ST 3000) · `400000` (2025, bin BTA14, ST 2000)

## Warehouse Resources
38 resources in RG01/RT01, queues: INBOUND, INTERNAL, PICOUNT
