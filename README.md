# Warehouse Agent — SAP S/4HANA EWM

AI chat agent for SAP S/4HANA EWM warehouse operations.
Built on **A2A** (JSON-RPC 2.0) + **LangGraph** + an LLM via **SAP AI Core**.

> **Custom A2A agent — not a SAP Joule native agent.**  
> No Joule Studio login required. Users interact via the Chat UI or MCP proxy.
> Point it at any SAP backend by setting the `S4HANA_DESTINATION_NAME` environment variable.

---

## Deployment — max-na-industry-us10 (Training)

| | |
|---|---|
| **BTP Subaccount** | max-na-industry-us10 |
| **CF API** | https://api.cf.us10.hana.ondemand.com |
| **CF Org** | max-na-industry-us10-cf |
| **SAP Backend Destination** | `S4X-100` (pre-configured, OnPremise via CC location `UXM`) |
| **CF services** | `whse-destination`, `whse-connectivity` |
| **Manifest** | copy `manifest-fgf.yml` → update `routes` + env vars |

### CF Deployment

```bash
cf api https://api.cf.us10.hana.ondemand.com
cf login --sso-passcode <code>      # passcode from: login.cf.us10.hana.ondemand.com/passcode
cf target -o max-na-industry-us10-cf -s <your-space>
cf push -f <your-manifest>.yml      # agent backend
```

The **Chat UI** (`warehouse-agent-ui`) is a separate CF app — see [Chat UI](#chat-ui) below.

---

## Skills (13 total)

Each `skills/<name>/SKILL.md` holds the skill description and sample utterances loaded at agent startup
via [`load_skill_resources.py`](load_skill_resources.py). These drive in-context intent routing — they are
not Joule skill flows.

| # | Skill | Folder | What it does |
|---|-------|--------|--------------|
| 1 | MM Stock Query | [`warehouse-stock-skill`](skills/warehouse-stock-skill/SKILL.md) | Plant/SLoc/batch stock (`API_MATERIAL_STOCK_SRV`) |
| 2 | EWM Stock Query | [`ewm-stock-skill`](skills/ewm-stock-skill/SKILL.md) | Bin-level available + physical stock in an EWM warehouse |
| 3 | Cross-Warehouse Stock | [`cross-warehouse-stock-skill`](skills/cross-warehouse-stock-skill/SKILL.md) | EWM physical stock across all warehouses in one call |
| 4 | Warehouse Orders & Tasks | [`warehouse-order-skill`](skills/warehouse-order-skill/SKILL.md) | EWM WO/WT query, filter, detail |
| 5 | Warehouse Task Confirmation | [`warehouse-task-confirm-skill`](skills/warehouse-task-confirm-skill/SKILL.md) | Confirm EWM tasks with qty/bin (needs approval) |
| 6 | Inbound Deliveries | [`warehouse-inbound-delivery-skill`](skills/warehouse-inbound-delivery-skill/SKILL.md) | Delivery headers, items, doc flow |
| 7 | EWM Outbound Deliveries | [`ewm-outbound-skill`](skills/ewm-outbound-skill/SKILL.md) | Outbound delivery orders from WH perspective |
| 8 | Storage Bins | [`storage-bin-skill`](skills/storage-bin-skill/SKILL.md) | Bin master data, fixed assignments, empty bins |
| 9 | Goods Movement & GR Posting | [`warehouse-goods-movement-skill`](skills/warehouse-goods-movement-skill/SKILL.md) | Material-doc history + post GR mvt 101 (needs approval) |
| 10 | EWM Physical Inventory | [`ewm-physical-inventory-skill`](skills/ewm-physical-inventory-skill/SKILL.md) | PI documents and count items in an EWM warehouse |
| 11 | Production Orders | [`production-order-skill`](skills/production-order-skill/SKILL.md) | Order status, BOM components, routing operations |
| 12 | Stock Transfer (no delivery) | [`sto-nodel-skill`](skills/sto-nodel-skill/SKILL.md) | One-shot STO → GI 351 → GR 101, no inbound delivery |
| 13 | EWM Inbound Delivery Goods Receipt | [`ewm-inbound-gr-skill`](skills/ewm-inbound-gr-skill/SKILL.md) | GR against EWM inbound delivery — full/partial (A2X OData V4) + HU-level (custom FM `Z_EWM_GR_HU_POST`) |

Full sample prompts: [`skills/SKILLS_OVERVIEW.md`](skills/SKILLS_OVERVIEW.md)

---

## Tools (48 domain tools)

Registered in [`tools/__init__.py`](tools/__init__.py) via `build_domain_tools()`; two destination tools
(`switch_destination`, `get_active_destination`) are added per session in [`agent.py`](agent.py).

| Group | Module | Tools |
|-------|--------|-------|
| MM Stock (V2) | [`stock_tools`](tools/stock_tools.py) | `get_material_stock`, `get_stock_overview` |
| Inbound Delivery (V2) | [`inbound_delivery_tools`](tools/inbound_delivery_tools.py) | `get_inbound_deliveries`, `get_inbound_delivery_detail`, `get_delivery_items`, `get_delivery_doc_flow` |
| Goods Movements (V2) | [`goods_movement_tools`](tools/goods_movement_tools.py) | `get_material_documents`, `post_goods_receipt` |
| STO Transfer no-delivery | [`goods_movement_tools`](tools/goods_movement_tools.py) | `create_sto`, `post_sto_goods_issue`, `post_sto_goods_receipt_no_del`, `execute_sto_transfer` |
| EWM WO & Task (V4) | [`warehouse_order_tools`](tools/warehouse_order_tools.py) | `get_warehouse_orders`, `get_warehouse_tasks`, `get_warehouse_task_detail` |
| EWM Stock (V4) | [`ewm_stock_tools`](tools/ewm_stock_tools.py) · [`cross_warehouse_stock_tools`](tools/cross_warehouse_stock_tools.py) | `get_ewm_available_stock`, `get_ewm_physical_stock`, `get_cross_warehouse_stock` |
| EWM Task Confirmation (V4 action) | [`warehouse_task_confirm_tools`](tools/warehouse_task_confirm_tools.py) | `confirm_warehouse_task`, `confirm_warehouse_task_exact` |
| EWM Outbound (V4) | [`ewm_outbound_tools`](tools/ewm_outbound_tools.py) | `get_ewm_outbound_deliveries`, `get_ewm_outbound_delivery_items` |
| Storage Bin (V4) | [`storage_bin_tools`](tools/storage_bin_tools.py) | `get_storage_bins`, `get_fixed_bin_assignments` |
| EWM Physical Inventory (V4) | [`ewm_physical_inventory_tools`](tools/ewm_physical_inventory_tools.py) | `get_phys_inventory_docs`, `get_phys_inventory_count_items` |
| EWM Inbound GR (A2X V4) | [`ewm_inbound_gr_tools`](tools/ewm_inbound_gr_tools.py) | `list_ewm_inbound_deliveries`, `get_ewm_inbound_delivery`, `post_ewm_inbound_gr` |
| EWM Warehouse Master (V4) | [`ewm_warehouse_tools`](tools/ewm_warehouse_tools.py) | `get_warehouses`, `get_storage_types` |
| EWM Resources (V4) | [`ewm_resource_tools`](tools/ewm_resource_tools.py) | `get_warehouse_resources`, `get_resource_group_queues` |
| Production Order — read (BAPI/SOAP) | [`production_order_tools`](tools/production_order_tools.py) | `get_production_order`, `get_production_order_components`, `get_production_order_operations`, `get_production_confirmations` |
| Production Order — read (V2) | [`production_order_odata_tools`](tools/production_order_odata_tools.py) | `get_production_orders_odata`, `get_production_order_status_odata`, `get_production_order_components_odata`, `get_production_order_operations_odata` |
| Production Execution — write (V2) | [`production_execution_tools`](tools/production_execution_tools.py) | `post_goods_issue_production`, `post_production_confirmation`, `post_goods_receipt_production` |
| Purchase Orders / STOs (V4) | [`purchase_order_tools`](tools/purchase_order_tools.py) | `get_purchase_orders`, `get_po_details` |
| Batch Management (V2) | [`batch_tools`](tools/batch_tools.py) | `search_batches`, `get_batch_classification` |
| Session / Destination | [`destination_tools`](tools/destination_tools.py) | `switch_destination`, `get_active_destination` |

---

## Agent Type — Custom A2A (not a Joule native agent)

This is a **custom agent** built on the A2A protocol (JSON-RPC 2.0). It is **not** a SAP Joule native agent
and does not require a Joule Studio login. Users interact with it directly via:
- the Chat UI (`warehouse-agent-ui`)
- the MCP proxy (`mcp_proxy/`) from Claude Code, Joule Desktop, or any MCP client

Each `skills/<name>/SKILL.md` defines the skill description and sample utterances. These are loaded at agent
startup as in-context instructions for intent routing — they are not Joule skill flows. The same description
text can optionally be used if you register the A2A endpoint as an external action in Joule Studio, but that
is not required for the agent to function.

---

## Chat UI

The chat UI (`warehouse-agent-ui`) is a separate CF app: a tiny Node/Express server (`server.js` →
`express.static('public')`) that serves a **static `public/index.html`** and proxies chat POSTs to the A2A
backend (`AGENT_HOST` env var). The rich **"All Skills & Prompts"** catalog and the **Quick Actions** sidebar
live in that static HTML — **not** in this repo and **not** produced by a build.

To deploy or update the catalog:
```bash
# Pull current catalog from a running CF app
cf download-droplet warehouse-agent-ui -p x.tgz
tar xzf x.tgz app/public/index.html app/server.js app/package.json
# Edit app/public/index.html → push with a manifest matching your route + AGENT_HOST
cf push -f <your-ui-manifest>.yml
```

**Catalog structure inside `index.html`:** sidebar quick-action = `<button class="action-item"
onclick="sendAction('<prompt>')">`; modal card = `<div class="skill-card">` with
`<li class="skill-prompt" onclick="usePrompt('<prompt>')">`.

UI features: plain HTML shell, UI5 Web Components CDN for CSS tokens only, collapsible Skills + Quick Actions
sidebar, SAP status strip (`[S]`/`[E]`/`[W]` detection + confirmation prompts), `marked.js` markdown,
`localStorage` history, per-response copy button.

### Desktop floating widget
[`floating_icon.pyw`](floating_icon.pyw) — a draggable transparent tkinter widget for the Windows desktop
(usable while SAP GUI is in the foreground). Run with `pythonw.exe floating_icon.pyw`; add to the
Windows Startup folder (`shell:startup`) so it launches automatically on every login.

| Action | Effect |
|--------|--------|
| **Ctrl+Alt+W** | Show / hide the SAP circle from anywhere (global hotkey) |
| **Click circle** | Open compact chat popup |
| **⊟ in popup header** | Hide entire widget (same as Ctrl+Alt+W) |
| **🌐 in popup header** | Open warehouse-agent-ui in browser |
| **✕ in popup header** | Close popup only (circle stays) |
| **Right-click → Quit** | Fully exit |

### MCP Proxy (Joule Desktop / Claude Code integration)

[`mcp_proxy/warehouse_mcp.py`](mcp_proxy/warehouse_mcp.py) — a **FastAPI MCP server** that exposes the
warehouse agent as a single MCP tool (`ask_warehouse_agent`) over the MCP 2025-03-26 Streamable HTTP
transport. Run it locally so any MCP client (SAP Joule Desktop, Claude Code, Cursor…) can talk to the CF
backend without browser auth.

**Start the proxy:**

```bat
mcp_proxy\start_mcp.bat          # visible terminal (shows logs)
pythonw mcp_proxy\start_mcp.pyw  # silent background launch
```

| Endpoint | URL |
|----------|-----|
| MCP | `http://localhost:8766/mcp` |
| Health | `http://localhost:8766/health` |

**Register in Joule Desktop:** Settings → MCP Servers → Add Server  
Name: `Warehouse Agent` · URL: `http://localhost:8766/mcp`

**Register in Claude Code** — copy `.mcp.json.template` → `.mcp.json` and fill in credentials (see
[Trainee Guide](references/TRAINEE_GUIDE.md#03-adt-mcp-abap-development-mcp-server)).

---

## Architecture

```
Browser → warehouse-agent-ui (Node/Express, static public/index.html)
              ↓ proxy POST /
          warehouse-agent (Python A2A)
              ↓ LangGraph agent loop
          LLM via SAP AI Core (aicore destination)
              ↓ tool calls
          SAP OData / BAPI APIs
              via BTP Destination Service
              via BTP Connectivity Proxy → Cloud Connector → S/4HANA
```

**Key proxy detail:** `httpx.Proxy(url, headers={...})` sends `Proxy-Authorization` and
`SAP-Connectivity-SCC-Location_ID` as proper proxy headers — required for Cloud Connector setups
with a non-default Location ID.

---

## Environment Variables

| Variable | Value (max-na-industry-us10) | Purpose |
|----------|------------------------------|---------|
| `S4HANA_DESTINATION_NAME` | `S4X-100` | SAP backend BTP destination |
| `DESTINATION_NAME` | `S4X-100` | same (legacy alias) |
| `AICORE_DESTINATION_NAME` | `aicore` | LLM via AI Core |
| `AGENT_NAME` | `S4X-100` | Display name in agent card |
| `AGENT_LLM_MODEL` | `gpt-4.1` | LLM model |
| `LOG_LEVEL` | `INFO` | Log verbosity |

---

## Demo Values (S4X-100 — system `s4x.uxm.sap.com`, client 100)

| Field | Value |
|-------|-------|
| Demo material | `PROJVECTDEMO` |
| Demo batch | `DEMO01` |
| Supplying plant / SLoc | `AM01` / `AM1A` |
| Receiving plant / SLoc | `AM02` / `171A` |

See [`references/s4x100-apis.md`](references/s4x100-apis.md) for confirmed active OData services on S4X-100.

---

## Trainee Onboarding

See [`references/TRAINEE_GUIDE.md`](references/TRAINEE_GUIDE.md) for the full onboarding guide:
prerequisites (CF CLI, BTP CLI, ADT MCP), BTP subaccount coordinates, CF deploy steps,
skill descriptions, tool reference, and API quick reference.
