# Warehouse Agent — Trainee Reference Guide

Use this document to build your own warehouse agent by forking and extending the work done in this project.
All links, BTP coordinates, skill definitions, APIs, and demo data you need are here.

> **Note:** This is a **custom A2A agent** (JSON-RPC 2.0 + LangGraph + SAP AI Core). It is not a SAP Joule native agent and does not require a Joule Studio login. Users interact with it directly via the Chat UI or the MCP proxy.

---

## 0 · Prerequisites & Toolchain Setup

Install these tools **once** after cloning the repo. All three are needed for full development — CF deployment, BTP administration, and ABAP development via Claude Code.

### 0.1 CF CLI (Cloud Foundry)

Required for `cf push` / `cf logs` / `cf env`.

```bash
# Download: https://github.com/cloudfoundry/cli/releases/latest
# Windows: download cf8-installer.zip → extract cf.exe → add to PATH
cf --version
```

### 0.2 BTP CLI

Required for managing BTP services, entitlements, and subaccount administration beyond what the CF CLI covers (service instances, destinations, etc.).

```bash
# Download: https://tools.hana.ondemand.com/#cloud → "SAP BTP Command Line Interface"
# Windows: extract btp.exe → add to PATH
btp --version

# Login
btp login --url https://cli.btp.cloud.sap
# Global account: COENAMFGLIVE
# Subaccount:     max-na-industry-us10

# Useful commands
btp list accounts/subaccount
btp list services/instance --subaccount 2c3472d5-7b0c-4175-9360-5173097006fd
btp list security/user     --subaccount 2c3472d5-7b0c-4175-9360-5173097006fd
```

### 0.3 ADT MCP (ABAP Development MCP Server)

Required for ABAP development with Claude Code — connects Claude to the S4X-100 ABAP system so you can read/write ABAP classes, programs, and CDS views directly from the IDE.

```bash
# Install (Node.js ≥ 18 required)
npm install -g @sap/mcp-abap-adt

# Verify
mcp-abap-adt --version
```

Copy `.mcp.json.template` → `.mcp.json` in the repo root and fill in the S4X-100 credentials:

```bash
cp .mcp.json.template .mcp.json
# edit .mcp.json → set user and password for S4X-100
```

`.mcp.json` is gitignored (contains credentials). Once configured, Claude Code will automatically connect to S4X-100 when you open this repo.

---

## 1 · Source Repository

```bash
git clone https://github.tools.sap/I584630/WarehouseAgent.git
```

---

## 2 · BTP Subaccount — max-na-industry-us10 (Training)

Use this subaccount for your agent deployment during development and training.

| | |
|---|---|
| **Subaccount** | max-na-industry-us10 |
| **Subdomain** | max-na-industry-us10 |
| **Tenant / Subaccount ID** | `2c3472d5-7b0c-4175-9360-5173097006fd` |
| **Region** | US East (VA) — AWS |
| **CF API Endpoint** | https://api.cf.us10.hana.ondemand.com |
| **CF Org ID** | `639f672b-8bca-48c0-8807-146337b2f1a6` |
| **CF Org Name** | `max-na-industry-us10-cf` |

### CF Login (training subaccount)

```bash
cf api https://api.cf.us10.hana.ondemand.com
cf login --sso-passcode <code>    # passcode from: login.cf.us10.hana.ondemand.com/passcode
cf target -o max-na-industry-us10-cf -s <your-space>
```

### SAP Backend Destination — S4X-100

All custom agents in this subaccount use the **`S4X-100`** destination. Set `S4HANA_DESTINATION_NAME=S4X-100` in every agent's CF manifest.

| Property | Value |
|----------|-------|
| **Destination name** | `S4X-100` |
| **Description** | S4X-100 GCLP |
| **Type** | HTTP |
| **Proxy Type** | OnPremise (via BTP Connectivity → Cloud Connector) |
| **URL** | `http://s4x.uxm.sap.com:80` |
| **Proxy Protocol** | HTTP |
| **Location ID** | `UXM` |
| **Authentication** | BasicAuthentication |
| **User** | `UXARCHITECT` |

The destination is already configured in the subaccount — no setup required. Check connection status in BTP Cockpit → Connectivity → Destinations → `S4X-100`.

---

## 3 · Agent Architecture

```
Browser / Chat UI
        │
        ▼
warehouse-agent-ui  (Node/Express, CF app)
  └─ public/index.html  — static skills catalog + quick-action sidebar
  └─ POST /  → proxy to A2A backend
        │
        ▼
warehouse-agent  (Python, CF app — this repo)
  ├─ A2A JSON-RPC 2.0 server (agent.py)
  ├─ LangGraph agent loop
  ├─ 13 skill SKILL.md files  → intent-matching descriptions
  ├─ 48 domain tool functions → OData / BAPI calls
  └─ LLM via SAP AI Core (aicore destination)
        │
        ▼
SAP OData / BAPI APIs
  via BTP Destination Service
  via BTP Connectivity Proxy → Cloud Connector → S/4HANA
```

### BTP services required in your subaccount

| Service | Instance name (example) | Purpose |
|---------|-------------------------|---------|
| Destination Service | `whse-destination` | Resolves named destinations |
| Connectivity Service | `whse-connectivity` | Cloud Connector proxy |
| AI Core | `aicore` destination | LLM inference |

### CF manifest environment variables

| Variable | Value for max-na-industry-us10 | Purpose |
|----------|-------------------------------|---------|
| `S4HANA_DESTINATION_NAME` | `S4X-100` | SAP backend destination (pre-configured in subaccount) |
| `AICORE_DESTINATION_NAME` | `aicore` | AI Core service destination |
| `AGENT_NAME` | `<your-system>` | Display name in agent card |
| `AGENT_LLM_MODEL` | `gpt-4.1` | LLM model identifier |
| `LOG_LEVEL` | `INFO` | Log verbosity |

---

## 4 · Skills (13 total)

Each skill lives in `skills/<folder>/SKILL.md`. The `description` frontmatter is the intent-matching text the agent uses to decide which skill applies. Skills are loaded at agent startup by `load_skill_resources.py`.

### 4.1 MM Stock Query
**Folder:** `skills/warehouse-stock-skill/`  
**API:** `API_MATERIAL_STOCK_SRV` (OData V2)  
**Key entity:** `A_MatlStkInAcctMod` (not `A_MaterialStock`)  
> ⚠️ EWM-managed plants return HTTP 500 — use EWM Stock (4.2) for those.

```
Show stock for material <matnr> in plant <plant>
What is the stock overview for <matnr>?
List all batches for material <matnr> in plant <plant>
```

### 4.2 EWM Stock Query
**Folder:** `skills/ewm-stock-skill/`  
**APIs:** `API_WHSE_AVAILABLESTOCK`, `API_WHSE_PHYSSTOCKPROD` (OData V4)

```
Show available stock for product <matnr> in storage type <stype> in warehouse <wh>
List all unrestricted stock in warehouse <wh>
Show stock in bin <bin> in warehouse <wh>
```

### 4.3 Cross-Warehouse Stock
**Folder:** `skills/cross-warehouse-stock-skill/`  
**API:** `API_WHSE_PHYSSTOCKPROD` (OData V4) — queries all warehouses in one call

```
Show stock for product <matnr> across all warehouses
Which warehouses have stock for product <matnr>?
Compare stock for <matnr> in warehouses <wh1> and <wh2>
```

### 4.4 Warehouse Orders & Tasks
**Folder:** `skills/warehouse-order-skill/`  
**API:** `API_WAREHOUSE_ORDER_TASK_2` (OData V4)  
> ⚠️ V4 response envelope is `{"value":[...]}` — not `d.results`.

```
List open warehouse orders in warehouse <wh>
Show warehouse tasks for order <wo-number>
What tasks are in queue INBOUND for warehouse <wh>?
```

### 4.5 Warehouse Task Confirmation
**Folder:** `skills/warehouse-task-confirm-skill/`  
**API:** SOAP RFC `/SCWM/TO_CONFIRM`  
> ⚠️ Mandatory yes/no confirmation gate before executing. Never skip.

```
Confirm warehouse task in order <wo-number> with exact quantity
Confirm task with actual quantity to bin <bin>
```

### 4.6 Inbound Deliveries
**Folder:** `skills/warehouse-inbound-delivery-skill/`  
**API:** `API_INBOUND_DELIVERY_SRV;v=0002` (OData V2)  
> ⚠️ `ReceivingPlant` is always blank on headers — filter by plant via **items**, not headers.

```
List inbound deliveries for plant <plant>
Show items for inbound delivery <delivery-number>
What is the document flow for delivery <delivery-number>?
```

### 4.7 EWM Outbound Deliveries
**Folder:** `skills/ewm-outbound-skill/`  
**API:** `API_WHSE_OUTB_DELIVERY_ORDER_2` (OData V4)  
> ⚠️ Always use explicit `$select` to avoid HTTP 500 from a missing DB column.

```
List outbound deliveries in warehouse <wh>
Show open ODOs in <wh>
List outbound delivery items for warehouse <wh>
```

### 4.8 Storage Bins
**Folder:** `skills/storage-bin-skill/`  
**APIs:** `API_WHSE_STORAGE_BIN_2`, `API_WHSE_FIXBIN_ASSGNMNT` (OData V4)

```
Show bin <bin> in warehouse <wh>
List all bins in storage type <stype> in <wh>
Show empty bins in storage type <stype> in <wh>
```

### 4.9 Goods Movement & GR Posting
**Folder:** `skills/warehouse-goods-movement-skill/`  
**API:** `API_MATERIAL_DOCUMENT_SRV` (OData V2)  
> ⚠️ Field name is `Delivery` (not `DeliveryDocument`) for delivery reference filters.

```
Show goods movements for material <matnr> in plant <plant>
List goods receipts (mvt 101) for plant <plant>
Post goods receipt for inbound delivery at plant <plant>
```

### 4.10 EWM Physical Inventory
**Folder:** `skills/ewm-physical-inventory-skill/`  
**API:** `API_WHSE_PHYSINVTRYITEM_2` (OData V4)  
Status codes: `ACTI`=Active · `COMP`=Completed · `CANC`=Cancelled · `CRTD`=Created

```
List active physical inventory documents in warehouse <wh>
Get count items for physical inventory document <doc-number>
Are there any open inventory documents for product <matnr>?
```

### 4.11 Production Orders
**Folder:** `skills/production-order-skill/`  
**API:** `API_PRODUCTION_ORDER_2_SRV` (OData V2)

```
List released production orders for plant <plant>
Show details for production order <order>
Show components for production order <order>
Give me a full picture of production order <order> — status, components, and operations
```

### 4.12 Stock Transfer (no inbound delivery)
**Folder:** `skills/sto-nodel-skill/`  
**Route:** Create STO → GI mvt 351 → GR mvt 101 — no inbound delivery  
**One-shot tool:** `execute_sto_transfer` — full flow in a single call after one confirmation

```
Transfer <qty> <uom> of <matnr> from <supplying-plant> to <receiving-plant>
Post GI 351 then GR 101 for STO <sto-number>
```

### 4.13 EWM Inbound Delivery Goods Receipt
**Folder:** `skills/ewm-inbound-gr-skill/`  
**APIs:** `API_WAREHOUSE_INBOUNDDELIVERY` A2X (OData V4) for full/partial GR; custom FM `Z_EWM_GR_HU_POST` for HU-level GR  
> ⚠️ Requires one explicit confirmation before posting.

```
Read EWM inbound delivery <delivery-number> and its items
Post full goods receipt for EWM inbound delivery <delivery-number>
Post partial GR for delivery <delivery-number>: item 10 = <qty> <uom>
Post GR for handling unit <hu-id> on delivery <delivery-number>
```

---

## 5 · Tools (48 domain tools)

Registered in `tools/__init__.py` via `build_domain_tools()`.

| Group | Module | Tools |
|-------|--------|-------|
| MM Stock (V2) | `stock_tools.py` | `get_material_stock`, `get_stock_overview` |
| Inbound Delivery (V2) | `inbound_delivery_tools.py` | `get_inbound_deliveries`, `get_inbound_delivery_detail`, `get_delivery_items`, `get_delivery_doc_flow` |
| Goods Movements (V2) | `goods_movement_tools.py` | `get_material_documents`, `post_goods_receipt` |
| STO Transfer (no delivery) | `goods_movement_tools.py` | `create_sto`, `post_sto_goods_issue`, `post_sto_goods_receipt_no_del`, `execute_sto_transfer` |
| EWM WO & Task (V4) | `warehouse_order_tools.py` | `get_warehouse_orders`, `get_warehouse_tasks`, `get_warehouse_task_detail` |
| EWM Stock (V4) | `ewm_stock_tools.py` · `cross_warehouse_stock_tools.py` | `get_ewm_available_stock`, `get_ewm_physical_stock`, `get_cross_warehouse_stock` |
| EWM Task Confirm (V4 action) | `warehouse_task_confirm_tools.py` | `confirm_warehouse_task`, `confirm_warehouse_task_exact` |
| EWM Outbound (V4) | `ewm_outbound_tools.py` | `get_ewm_outbound_deliveries`, `get_ewm_outbound_delivery_items` |
| Storage Bin (V4) | `storage_bin_tools.py` | `get_storage_bins`, `get_fixed_bin_assignments` |
| EWM Physical Inventory (V4) | `ewm_physical_inventory_tools.py` | `get_phys_inventory_docs`, `get_phys_inventory_count_items` |
| EWM Inbound GR (A2X V4) | `ewm_inbound_gr_tools.py` | `list_ewm_inbound_deliveries`, `get_ewm_inbound_delivery`, `post_ewm_inbound_gr` |
| EWM Warehouse Master (V4) | `ewm_warehouse_tools.py` | `get_warehouses`, `get_storage_types` |
| EWM Resources (V4) | `ewm_resource_tools.py` | `get_warehouse_resources`, `get_resource_group_queues` |
| Production Order read (BAPI) | `production_order_tools.py` | `get_production_order`, `get_production_order_components`, `get_production_order_operations`, `get_production_confirmations` |
| Production Order read (V2) | `production_order_odata_tools.py` | `get_production_orders_odata`, `get_production_order_status_odata`, `get_production_order_components_odata`, `get_production_order_operations_odata` |
| Production Execution write (V2) | `production_execution_tools.py` | `post_goods_issue_production`, `post_production_confirmation`, `post_goods_receipt_production` |
| Purchase Orders / STOs (V4) | `purchase_order_tools.py` | `get_purchase_orders`, `get_po_details` |
| Batch Management (V2) | `batch_tools.py` | `search_batches`, `get_batch_classification` |
| Session / Destination | `destination_tools.py` | `switch_destination`, `get_active_destination` |

---

## 6 · OData API Quick Reference

| Service | Version | Base Path |
|---------|---------|-----------|
| `API_MATERIAL_STOCK_SRV` | V2 | `/sap/opu/odata/sap/API_MATERIAL_STOCK_SRV` |
| `API_INBOUND_DELIVERY_SRV;v=0002` | V2 | `/sap/opu/odata/sap/API_INBOUND_DELIVERY_SRV;v=0002` |
| `API_MATERIAL_DOCUMENT_SRV` | V2 | `/sap/opu/odata/sap/API_MATERIAL_DOCUMENT_SRV` |
| `API_WAREHOUSE_ORDER_TASK_2` | V4 | `/sap/opu/odata4/sap/api_warehouse_order_task/srvd_a2x/sap/api_warehouse_order_task/0002` |
| `API_WHSE_AVAILABLESTOCK` | V4 | `/sap/opu/odata4/sap/api_whse_availablestock/srvd_a2x/sap/api_whse_availablestock/0001` |
| `API_WHSE_PHYSSTOCKPROD` | V4 | `/sap/opu/odata4/sap/api_whse_physstockprod/srvd_a2x/sap/api_whse_physstockprod/0001` |
| `API_WHSE_OUTB_DELIVERY_ORDER_2` | V4 | `/sap/opu/odata4/sap/api_warehouse_odo/srvd_a2x/sap/api_warehouse_odo/0002` |
| `API_WHSE_STORAGE_BIN_2` | V4 | `/sap/opu/odata4/sap/api_whse_storage_bin/srvd_a2x/sap/api_whse_storage_bin/0002` |
| `API_WHSE_FIXBIN_ASSGNMNT` | V4 | `/sap/opu/odata4/sap/api_whse_fixbin_assgnmnt/srvd_a2x/sap/api_whse_fixbin_assgnmnt/0001` |
| `API_WHSE_PHYSINVTRYITEM_2` | V4 | `/sap/opu/odata4/sap/api_whse_physinvtryitem/srvd_a2x/sap/api_whse_physinvtryitem/0002` |
| `API_WAREHOUSE_INBOUNDDELIVERY` (A2X) | V4 | `/sap/opu/odata4/sap/api_warehouse_inbounddelivery/srvd_a2x/sap/api_warehouse_inbounddelivery/0001` |
| `API_PRODUCTION_ORDER_2_SRV` | V2 | `/sap/opu/odata/sap/API_PRODUCTION_ORDER_2_SRV` |
| `/SCWM/TO_CONFIRM` | SOAP | via BTP SOAP-RFC bridge |

All APIs are standard SAP S/4HANA public APIs — activate the relevant communication scenario in your system (e.g. `SAP_COM_0164` for EWM, `SAP_COM_0109` for Production Orders).

---

## 7 · Quick-Start Checklist

Follow this order when setting up your own agent in the training subaccount (`max-na-industry-us10`):

- [ ] Install prerequisites (section 0): CF CLI, BTP CLI, ADT MCP — see `references/TRAINEE_GUIDE.md §0`
- [ ] Clone the repo: `git clone https://github.tools.sap/I584630/WarehouseAgent.git`
- [ ] Log in to BTP CF: `cf api https://api.cf.us10.hana.ondemand.com` → `cf login --sso-passcode …`
- [ ] Target the training org: `cf target -o max-na-industry-us10-cf -s <your-space>`
- [ ] Destination `S4X-100` is already configured in the subaccount — verify via BTP Cockpit → Destinations
- [ ] Create BTP service instances: Destination Service + Connectivity Service (bind to your CF app)
- [ ] Copy `manifest-fgf.yml` → rename and update: `routes`, `AGENT_NAME`, and set `S4HANA_DESTINATION_NAME: S4X-100`
- [ ] `cf push -f <your-manifest>.yml`
- [ ] Verify the agent card: `GET https://<your-route>/.well-known/agent.json`
- [ ] Test via Chat UI or MCP proxy — **no Joule login required**
- [ ] (Optional) Deploy the Chat UI (`warehouse-agent-ui`) with `AGENT_HOST` pointing at your agent route
- [ ] (Optional) Register the agent as an MCP tool in Claude Code or Joule Desktop via the MCP proxy (`mcp_proxy/`)
