# Warehouse Agent — SAP S/4HANA EWM

AI chat agent for SAP S/4HANA EWM warehouse operations.
Built on **A2A** (JSON-RPC 2.0) + **LangGraph** + an LLM via **SAP AI Core** (orchestration on FGF, GPT-4o elsewhere).

The agent is multi-tenant: the same codebase is deployed to several BTP subaccounts, each pointing at a
different SAP backend via its own destination + Cloud Connector. **FGF Brands / D4H-200 (warehouse `PBAR`,
plant `BAR1`) is the current primary system.**

---

## Deployments

| Tenant | Purpose | Backend | Warehouse / Plant |
|--------|---------|---------|-------------------|
| **FGF Brands — D4H-200** | **Primary (current)** | `D4H` client 200 via `SBPA_d4hclnt200` | `PBAR` / `BAR1` |

### FGF Brands — D4H-200  ⭐ primary

| | Link |
|---|---|
| Chat UI | https://warehouse-agent-ui.cfapps.us10-001.hana.ondemand.com |
| A2A Agent | https://warehouse-agent.cfapps.us10-001.hana.ondemand.com |
| Agent Card | https://warehouse-agent.cfapps.us10-001.hana.ondemand.com/.well-known/agent.json |

- **BTP Subaccount:** FGFDev (`af7d8140-9729-4027-ba8e-073cf430f40f`)
- **CF API:** `https://api.cf.us10-001.hana.ondemand.com`
- **CF Org / Space:** `CPEA_- FGF Brands Inc._fgfdev-2sr0v4ay` / `dev` *(exact org spacing matters)*
- **Destination:** `SBPA_d4hclnt200` → `d4hci.sap.fgfbrands.com:44300` (HTTP, CC location `FGFDEV`)
- **CF services:** `whse-destination`, `whse-connectivity`
- **Manifest:** [`manifest-fgf.yml`](manifest-fgf.yml)
- **AI Core:** orchestration deployment `d83d244723732db0`, model `gpt-4.1` (see [`aicore.py`](aicore.py))
- **Joule Studio:** skills also registered here as triggerable Joule skills

---

## CF Deployment

```bash
# FGF Brands (D4H-200) — primary
cf api https://api.cf.us10-001.hana.ondemand.com
cf login --sso-passcode <code>            # from login.cf.us10-001.hana.ondemand.com/passcode
cf target -o "CPEA_- FGF Brands Inc._fgfdev-2sr0v4ay" -s dev
cd c:/mydata/JD/Joulewarehouse
cf push -f manifest-fgf.yml               # agent
```

The **Chat UI** (`warehouse-agent-ui`) is a separate CF app — see [Chat UI](#chat-ui) below.

---

## Skills (13 total)

Each `skills/<name>/SKILL.md` holds the skill description + sample utterances used for Joule intent matching;
they are loaded at agent startup via [`load_skill_resources.py`](load_skill_resources.py).

| # | Skill | Folder | What it does |
|---|-------|--------|--------------|
| 1 | MM Stock Query | [`warehouse-stock-skill`](skills/warehouse-stock-skill/SKILL.md) | Plant/SLoc/batch stock (`API_MATERIAL_STOCK_SRV`) |
| 2 | EWM Stock Query | [`ewm-stock-skill`](skills/ewm-stock-skill/SKILL.md) | Bin-level available + physical stock in WH `PBAR` |
| 3 | Cross-Warehouse Stock | [`cross-warehouse-stock-skill`](skills/cross-warehouse-stock-skill/SKILL.md) | EWM physical stock across all 34 warehouses in one call |
| 4 | Warehouse Orders & Tasks | [`warehouse-order-skill`](skills/warehouse-order-skill/SKILL.md) | EWM WO/WT query, filter, detail |
| 5 | Warehouse Task Confirmation | [`warehouse-task-confirm-skill`](skills/warehouse-task-confirm-skill/SKILL.md) | Confirm EWM tasks with qty/bin (needs approval) |
| 6 | Inbound Deliveries | [`warehouse-inbound-delivery-skill`](skills/warehouse-inbound-delivery-skill/SKILL.md) | Delivery headers, items, doc flow |
| 7 | EWM Outbound Deliveries | [`ewm-outbound-skill`](skills/ewm-outbound-skill/SKILL.md) | Outbound delivery orders from WH perspective |
| 8 | Storage Bins | [`storage-bin-skill`](skills/storage-bin-skill/SKILL.md) | Bin master data, fixed assignments, empty bins |
| 9 | Goods Movement & GR Posting | [`warehouse-goods-movement-skill`](skills/warehouse-goods-movement-skill/SKILL.md) | Material-doc history + post GR mvt 101 (needs approval) |
| 10 | EWM Physical Inventory | [`ewm-physical-inventory-skill`](skills/ewm-physical-inventory-skill/SKILL.md) | PI documents and count items in WH `PBAR` |
| 11 | Production Orders | [`production-order-skill`](skills/production-order-skill/SKILL.md) | Order status, BOM components, routing operations |
| 12 | Stock Transfer 3PL → FEN1 via IM | [`sto-nodel-skill`](skills/sto-nodel-skill/SKILL.md) | One-shot STO (ZIC3) → GI 351 → GR 101, no inbound delivery |
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

To edit the FGF catalog:
```bash
cf download-droplet warehouse-agent-ui -p x.tgz
tar xzf x.tgz app/public/index.html app/server.js app/package.json
# edit app/public/index.html → cf push -f <manifest matching live route + AGENT_HOST>
```
A pulled working copy is kept at `C:\mydata\JD\whse-ui-droplet\app\`.

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
| **Right-click → Quit** | Fully exit (relaunch manually or wait for next login) |
| **Ctrl+Alt+J** | Open popup + switch agent to D4H-200 |

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

**Register in Claude Code / cursor** — add to `.mcp.json`:
```json
{ "mcpServers": { "warehouse": { "url": "http://localhost:8766/mcp" } } }
```

---

## Architecture

```
Browser → warehouse-agent-ui (Node/Express, static public/index.html)
              ↓ proxy POST /
          warehouse-agent (Python A2A)
              ↓ LangGraph agent loop
          LLM via SAP AI Core (aicore destination; FGF = orchestration/gpt-4.1)
              ↓ tool calls
          SAP OData / BAPI APIs
              via BTP Connectivity Proxy → Cloud Connector → D4H-200
```

**Key fix (2026-08-14):** `httpx.Proxy(url, headers={...})` is used instead of `proxy=url_string` so that
`Proxy-Authorization` and `SAP-Connectivity-SCC-Location_ID` are sent as proper proxy headers, not request
headers — required for multi-location Cloud Connector setups.

---

## Environment Variables

| Variable | FGF (primary) | Purpose |
|----------|---------------|---------|
| `AICORE_DESTINATION_NAME` | `aicore` | LLM via AI Core |
| `S4HANA_DESTINATION_NAME` | `SBPA_d4hclnt200` | SAP backend destination |
| `DESTINATION_NAME` | `SBPA_d4hclnt200` | same (legacy alias) |
| `AGENT_NAME` | `D4H-200` | Display name in agent card |
| `AGENT_LLM_MODEL` | `gpt-4.1` | LLM model |
| `LOG_LEVEL` | `INFO` | Log verbosity |

---

## Demo Values (FGF / D4H-200 — WH `PBAR`, Plant `BAR1`)

| Field | Value |
|-------|-------|
| Materials (real) | `1010005` `1010010` `1010012` `1010016` `1010017` `1010019` `1010020` `1010028` `1111011` `1111039` `1111044` |
| Production-order materials | `5002731-01-00` `5002732-01-00` `5002939-00-00` `5007822-00-00` `5100669-00-01` |
| Sample production orders | `1001176` `1001177` `1001182` `1001214` `1001294` |
| Storage types | `1000` `2000` `3000` `4000` `9000` `9010` `9020` `CL01` `FLR` `TRLR` |
| Sample bins | `H13A2` `H13C2` `B20G1D` `C2B1` `GR-DOCK` `GI-ZONE` `J1C2` `H11B2` |
| Physical inventory docs | `400024` `400026` (2026, ST 3000) · `400000` (2025, ST 2000) |
| STO transfer (3PL→FEN1) | material `1313284`, `PRO6/2100` → `FEN1/2000` |
