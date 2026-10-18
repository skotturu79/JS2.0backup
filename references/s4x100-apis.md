# Active OData APIs — S4X-100 (gclp0353.devint.net.sap, client 100)

## Confirmed Active Services

| Service | Base Path | Key Entity Sets |
|---------|-----------|-----------------|
| `API_INBOUND_DELIVERY_SRV;v=0002` | `/sap/opu/odata/sap/API_INBOUND_DELIVERY_SRV;v=0002` | A_InbDeliveryHeader, A_InbDeliveryItem, A_InbDeliveryDocFlow, A_InbDeliveryPartner, A_HndlgUnitHdrForInbDeliv |
| `API_MATERIAL_STOCK_SRV` | `/sap/opu/odata/sap/API_MATERIAL_STOCK_SRV` | A_MaterialStock, A_MatlStkInAcctMod, A_MaterialSerialNumber |
| `API_MATERIAL_DOCUMENT_SRV` | `/sap/opu/odata/sap/API_MATERIAL_DOCUMENT_SRV` | A_MaterialDocumentHeader, A_MaterialDocumentItem |

## Confirmed Inactive / Not Found

| Service | Notes |
|---------|-------|
| `API_WAREHOUSE_ORDER_SRV` | EWM — not registered on this client |
| `API_EWM_WAREHOUSE_TASK` | EWM — not registered on this client |
| `API_WHSE_DELIVERYPROCESSING_SRV` | EWM — not registered |
| `API_WHSE_PRODUCT_STAGING_SRV` | EWM — not registered |
| `API_WAREHOUSE_REQUEST_SRV` | Not registered |
| `API_OUTBOUND_DELIVERY_SRV;v=0002` | Not registered (outbound delivery used via ICF handler in QM agent) |

## Key Filter Fields

### A_InbDeliveryHeader
- `ReceivingPlant` — filter by receiving plant
- `Vendor` — filter by vendor
- `OverallGoodsReceiptStatus` — A=not started, B=partial, C=complete

### A_MaterialStock
- `Material` — material number
- `Plant` — plant code
- `StorageLocation` — storage location
- `Batch` — batch number

### A_MaterialDocumentItem
- `Material`, `Plant`, `Batch` — standard filters
- `GoodsMovementType` — 101, 201, 261, 501, 551, 601, 641

## BTP Destination
- **Destination name:** `S4X-100`
- **Description:** S4X-100 GCLP
- **Type:** HTTP
- **Proxy type:** OnPremise (routes via BTP Connectivity / Cloud Connector)
- **URL:** `http://s4x.uxm.sap.com:80`
- **Proxy Protocol:** HTTP
- **Location ID:** `UXM`
- **Authentication:** BasicAuthentication
- **User:** `UXARCHITECT`

## Demo Values
- Material: `PROJVECTDEMO`
- Batch: `DEMO01`
- Supplying plant: `AM01` / SLoc: `AM1A`
- Receiving plant: `AM02` / SLoc: `171A`
