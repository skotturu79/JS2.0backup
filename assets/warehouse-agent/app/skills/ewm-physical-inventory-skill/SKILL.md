---
name: ewm-physical-inventory-skill
description: "Guides the agent to query EWM Physical Inventory documents and count items using OData V4 API_WHSE_PHYSINVTRYITEM_2 on S4X-100. Entities: WhsePhysicalInventoryItem, WhsePhysicalInventoryCountItem."
---

# EWM Physical Inventory Skill

## Service
- **System:** D4H-200 — `10.254.2.59:44300`, client 200
- **API:** API_WHSE_PHYSINVTRYITEM_2
- **Base URL:** /sap/opu/odata4/sap/api_whse_physinvtryitem_2/srvd_a2x/sap/api_whse_physinvtryitem_2/0001
- **Entities:** WhsePhysicalInventoryItem, WhsePhysicalInventoryCountItem, WhsePhysicalInventorySrlNmbr

## Tools
- `get_phys_inventory_docs` — list inventory document items; filter by doc number, year, bin, storage type, product, status
- `get_phys_inventory_count_items` — count items for a specific document

## Status Codes
- ACTI = Active
- COMP = Completed
- CANC = Cancelled
- CRTD = Created

## Sample Prompts
- "List active physical inventory documents in warehouse PBAR"
- "Show physical inventory documents for storage type 3000 in warehouse PBAR"
- "Get count items for physical inventory document 400024"
- "Are there any open inventory documents for product 1999904?"
- "Show frozen/blocked inventory documents in warehouse PBAR"

## Key Fields (WhsePhysicalInventoryItem)
- EWMWarehouse, PhysicalInventoryDocNumber, PhysicalInventoryDocYear
- PhysicalInventoryItemNumber, PhysicalInventoryDocumentType
- PhysicalInventoryStatusText (ACTI/COMP/CANC/CRTD)
- EWMStorageType, EWMStorageBin, Product, Batch, EWMStockType
- WarehouseOrder, PInvBookQuantityIsFreeze, PhysicalInventoryIsBlock

## Key Fields (WhsePhysicalInventoryCountItem)
- PhysicalInventoryDocNumber, PhysicalInventoryDocYear, PhysicalInventoryItemNumber
- LineIndexOfPInvItem, EWMStorageBin, EWMStorageType, Product, Batch
- RequestedQuantity, RequestedQuantityUnit
- PInvIsZeroCount (boolean), EWMStorageBinIsEmpty (boolean)

## Real Data (WH PBAR, D4H-200)
- Doc 400024 / Year 2026 — Type HS, Status ACTI, Storage Type 3000, Bin J1C2, Product 4999904
- Doc 400026 / Year 2026 — Type HS, Status ACTI, Storage Type 3000, Bin H11B2, Product 1999904
- Doc 400000 / Year 2025 — Type HL, Status ACTI, Storage Type 2000, Bin BTA14
