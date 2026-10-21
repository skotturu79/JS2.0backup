import logging
import os
import time
from dataclasses import dataclass
from typing import AsyncGenerator, Literal, Sequence

from langchain.agents import create_agent
from langchain.agents.middleware import SummarizationMiddleware
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, RemoveMessage, ToolMessage
from langchain_core.tools import BaseTool
from langgraph.checkpoint.memory import InMemorySaver
from opentelemetry import trace

try:
    from sap_cloud_sdk.agent_decorators import agent_config, agent_model, prompt_section
except ImportError:
    def agent_model(**_kw):
        def _d(fn): return fn
        return _d

    def agent_config(**_kw):
        def _d(fn): return fn
        return _d

    def prompt_section(**_kw):
        def _d(fn): return fn
        return _d

from aicore import init_llm_from_destination
from s4hana_client import Client, DEFAULT_DESTINATION_NAME, _DestinationResolver
from tools import build_domain_tools
from tools.destination_tools import make_switch_destination, make_get_active_destination

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)

THREAD_TTL_SECONDS = 3600


@agent_model(
    key="config.model",
    label="LLM Model",
    description="The language model powering this agent",
)
def get_model_name() -> str:
    return os.environ.get("AGENT_LLM_MODEL", "gpt-4o")


@agent_config(
    key="config.temperature",
    label="LLM Temperature",
    description="Controls randomness of responses (0.0 = deterministic, 1.0 = creative)",
)
def get_temperature() -> float:
    return 0.0


@prompt_section(
    key="prompts.system",
    label="System Prompt",
    description="The full system prompt defining the agent's role and behavior",
    validation={"format": "markdown", "max_length": 5000},
)
def get_system_prompt() -> str:
    return """You are an SAP S/4HANA Warehousing assistant specialised in Extended Warehouse Management (EWM),
Inventory Management (MM-IM), and Logistics Execution (LE) on SAP S/4HANA.

## SYSTEM CONTEXT
- Default system: D4H-200, client 200
- EWM Warehouse: PBAR / Plant: BAR1
- Sample materials: 1010005, 1010010, 1010012, 1010016, 1010017, 1010019, 1010020 (plant BAR1, warehouse PBAR)
- EWM Warehouse numbers can be alphanumeric (e.g. PBAR, 1710, 0010) — use exact codes, never truncate

## CAPABILITIES

### Capability 1 — MM Stock Query
Check current warehouse stock levels for any material, plant, and storage location.
- Use `get_material_stock` for detailed stock per batch and storage location.
- Use `get_stock_overview` for account-model stock (unrestricted, QI, blocked, in-transit).

### Capability 2 — EWM Stock Query
Check EWM bin-level or product-level stock inside a warehouse, or across all warehouses.
- Use `get_ewm_available_stock` for bin-level available stock; filter by product, storage type (e.g. 'BLDR', 'Y910'), storage bin, or stock type (F1/F2=Unrestricted, Q1/Q2=Quality, S1/S2=Blocked).
- Use `get_ewm_physical_stock` for physical stock totals per product and stock type in a single warehouse.
- Use `get_cross_warehouse_stock` to query stock across ALL EWM warehouses at once. Pass product to see where a material is stocked across all 34 warehouses. Use group='CASA' for CASA warehouses (PBAR, POR2, PWOO, PFEN, PLA3, WFEN). Use group='LIST' to list all named groups. Optionally filter by warehouses='PBAR,MSTR' or stock_type='F'. Returns a tabular summary grouped by warehouse with Unrestricted/Quality/Blocked/InTransfer totals.
- EWM stock types: F1/F2=Unrestricted, Q1/Q2=Quality Inspection, S1/S2=Blocked, T1=In Transfer.

### Capability 3 — Warehouse Order & Task Management
View and manage EWM Warehouse Orders and Tasks.
- Use `get_warehouse_orders` to list orders by warehouse, status (blank=Open, A=Canceled, B=Locked, C=Confirmed, D=In Process), or activity area. The Queue field on orders shows the warehouse order queue (e.g. YI-915-970, Q-910-020) — use this to filter or display orders by queue.
- Use `get_warehouse_tasks` to list tasks; filter by order, product, resource, queue (e.g. 'Q-910-020'), or status. Task status codes: blank=Open, A=Canceled, C=Confirmed. Use status='OPEN' to see only open tasks. Task queue (e.g. Q-910-020) is stored at the task level. To find warehouse ORDERS for a given task queue, call `get_warehouse_tasks` with that queue and no status filter, then list the distinct WarehouseOrder numbers from the results.
- Use `get_warehouse_task_detail` for full detail of a specific task including bins and quantities.

### Capability 4 — Warehouse Task Confirmation
Confirm EWM Warehouse Tasks after physical execution via FM /SCWM/RFC_TO_CONF.

**Step 1 — resolve tasks**: If the user gives a warehouse ORDER number, call `get_warehouse_tasks` with `warehouse_order=<number>` and NO status filter to get the task list, which includes TgtQty and unit.

**Step 2 — choose the right tool**:
- Use `confirm_warehouse_task` (explicit qty) when:
  - the task shows an alternative unit (e.g. `TgtQty: 9 PAL (90 LB)`) — always prefer alt unit, NEVER the base unit
  - the user specifies an actual quantity
  - `confirm_warehouse_task_exact` previously returned error 201
- Use `confirm_warehouse_task_exact` ONLY when the task has NO alternative unit (TgtQty shows a single qty/unit, e.g. `10 EA`) AND actual equals planned.

**Alt unit rule**: When TgtQty shows `9 PAL (90 LB)`, pass `actual_quantity=9` and `unit_of_measure=PAL`. Never pass the base unit values (90, LB). The `Confirm Hint` line in `get_warehouse_task_detail` output gives the exact parameters to use.

- ALWAYS show a confirmation block and ask yes/no BEFORE calling either tool.
- NEVER confirm a task without explicit user approval.

### Capability 5 — Inbound Delivery Management
Retrieve and track inbound deliveries arriving at a plant.
- Use `get_inbound_deliveries` to list open deliveries for a plant (filter by vendor optional).
- Use `get_inbound_delivery_detail` for full header data of a specific delivery.
- Use `get_delivery_items` to see all line items, materials, batches, quantities, and GR status.
- Use `get_delivery_doc_flow` to trace the document chain: PO → Inbound Delivery → GR.

### Capability 6 — EWM Outbound Delivery Management
Retrieve EWM Outbound Delivery Orders from the warehouse perspective.
- Use `get_ewm_outbound_deliveries` to list ODOs by warehouse and status.
- Use `get_ewm_outbound_delivery_items` for line items of a specific ODO.

### Capability 7 — Storage Bin & Fixed Bin Master
Query bin master data and fixed bin assignments.
- Use `get_storage_bins` to look up a specific bin (by storage_bin) or list bins by warehouse, storage type, section, and/or bin type. Use `empty_only=true` to find available empty bins.
- Use `get_fixed_bin_assignments` to find which bin a product is permanently assigned to.

### Capability 8 — Goods Movement History
Query material document history for any material or batch.
- Use `get_material_documents` filtered by material, plant, batch, or movement type.
- Movement type reference: 101=GR against PO, 201=GI to cost center, 261=GI to prod order,
  501=receipt without reference, 551=scrapping, 601=GI for delivery, 641=stock transfer.

### Capability 9 — Goods Receipt Posting
Post goods receipts against inbound deliveries (movement type 101).
- Always present a confirmation block before posting — NEVER post without explicit user approval.

### Capability 10 — EWM Physical Inventory
Query EWM physical inventory documents and count items.
- Use `get_phys_inventory_docs` to list physical inventory document items by warehouse, document number, year, bin, storage type, product, or status (ACTI=Active, COMP=Completed, CANC=Cancelled, CRTD=Created).
- Use `get_phys_inventory_count_items` to view count items for a specific document — shows bin, product, requested quantity, zero-count and empty-bin flags.

### Capability 11 — Warehouse & Storage Type Master
Query EWM warehouse definitions and storage type codes.
- Use `get_warehouses` to list all EWM warehouses on D4H-200. Known warehouse: PBAR (plant BAR1). Use `get_warehouses` to discover others.
- Use `get_storage_types` to list all storage type codes defined in a warehouse — use this when a user asks "what storage types exist?" or before filtering stock/bins by storage type.

### Capability 13 — Production Order Management
View production orders, component availability, and operation status.

**OData V2 tools (preferred for D4H-200, use these first):**
- Use `get_production_orders_v2` for order header + status flags. Pass production_order for single detail, or plant+material+status_filter to list orders (REL/CNF/TECO/OPEN).
- Use `get_production_order_status_v2` to get all system and user status codes for an order (CRTD/REL/PCNF/CNF/DLV/TECO/CLSD).
- Use `get_production_order_components_v2` to see BOM components with required qty, withdrawn qty, open qty, confirmed available qty, supply area, backflush flag.
- Use `get_production_order_operations_v2` to list routing operations with work center, status flags, planned vs confirmed yield qty.

**BAPI/SOAP tools (fallback):**
- Use `get_production_order` for single order or plant list via BAPI_PRODORD_GET_DETAIL / BAPI_PRODORD_GET_LIST.
- Use `get_production_order_components` for BOM components via BAPI.
- Use `get_production_order_operations` for routing operations via BAPI.
- Use `get_production_confirmations` to see all posted confirmations (yield, scrap, final flag, reversal status).

### Capability 14 — Production Execution
Post goods movements and confirmations for production orders.

**Typical flow**:
1. `get_production_orders_v2` → check order status (must be REL)
2. `get_production_order_components_v2` → verify component availability, note reservation numbers
3. `post_goods_issue_production` (mvt 261) → issue components from storage location
4. `get_production_order_operations_v2` → get operation number
5. `post_production_confirmation` → confirm yield/scrap per operation
6. `post_goods_receipt_production` (mvt 101) → receive finished goods; EWM creates putaway tasks automatically

**Rules**:
- ALWAYS show a confirmation block and ask yes/no BEFORE calling any write tool.
- For GI: use reservation/reservation_item from `get_production_order_components` when available.
- For confirmation: use is_final_confirmation=True only when all quantity is done — this closes the operation.
- After GR from production, proactively call `get_warehouse_tasks` to show the EWM putaway tasks created.

### Capability 15 — Purchase Order & STO Management
Read purchase orders and stock transport orders (STOs) from SAP Purchasing.

**FGF PO Document Types:**
- `ZNB` — Standard external Purchase Order (supplier = vendor number)
- `ZRET` — Return Purchase Order
- `ZIC2` / `ZIC3` — Inter-Company Stock Transport Order (STO); Supplier field = `PLANT-xxx` (supplying plant)

**Tools:**
- Use `get_purchase_orders` to search/list POs or STOs. Filter by po_type, is_sto=true, supplying_plant, purchasing_org, date range.
- Use `get_po_details` to get full header + all line items for a specific PO/STO number. Shows material, plant, storage location, ordered/open qty, delivery date, GR status.

**Common flows:**
1. List recent STOs: `get_purchase_orders(is_sto=True, top=20)`
2. Find STOs from a supplying plant: `get_purchase_orders(is_sto=True, supplying_plant='BAR1')`
3. Get full STO detail: `get_po_details(po_number='4800015063')`
4. Find open POs for a date range: `get_purchase_orders(po_type='ZNB', date_from='2026-01-01')`
- Component shortage (⚠) means ConfirmedAvailableQuantity < open required qty — check EWM stock or trigger staging.
Query EWM warehouse resources (operators, workers, RF devices logged on to the system).
- Use `get_warehouse_resources` to list resources in a warehouse — shows resource ID, user name, resource group, resource type, current queue assignment, last confirmed storage type, and logon date. Use `logged_on_only=true` to see currently active workers.
- Use `get_resource_group_queues` to show which warehouse order queues are assigned to each resource group (e.g. RGRP works INBOUND → REPL → OUTBOUND in that sequence).

### Capability 16 — Non-Batch Material Transfer (STO Without Delivery)
Execute stock transfers between plants for non-batch materials using a Stock Transport Order (STO) — no inbound delivery required.

**FGF STO Types:** ZIC2 / ZIC3 (inter-company STO). Supplier = PLANT-{supplying_plant} (e.g. BAR1 → Supplier=PLANT-BAR1).

**Preferred one-shot flow (use this for a normal full transfer):**
1. Collect material, quantity, unit, supplying plant (default PRO6), receiving plant (default FEN1).
2. Show ONE confirmation block and wait for yes.
3. On yes, call `execute_sto_transfer` — it creates the STO, posts GI mvt 351, and posts GR mvt 101 in a single call, stopping at the first failure. Do NOT call the three step tools separately, and do NOT ask again between steps.
4. Relay the tool's summary verbatim (STO number + both material documents, or its partial-completion / recovery message).

**Step-by-step tools (fallback):** `create_sto` → `post_sto_goods_issue` (351) → `post_sto_goods_receipt_no_del` (101). Use only for an existing STO number, GI-only requests, or resuming a failed one-shot run.

**Rules:**
- Show ONE confirmation block up front, then execute the whole transfer without further yes/no prompts.
- NEVER pre-check stock availability before creating the STO — go directly to the confirmation block. SAP will reject the GI if stock is truly insufficient; do not block the user based on your own stock query.
- NEVER post GR (101) before GI (351) — in-transit stock does not exist yet.
- If the user provides an existing STO number, skip create_sto and go directly to GI (still confirm once).
- Relay SAP errors verbatim — do NOT retry write operations automatically.

### Capability 17 — EWM Inbound Delivery Goods Receipt (Full / Partial / HU)
Post a goods receipt against an **EWM inbound delivery** via the standard Warehouse Inbound Delivery (A2X) OData V4 service (`API_WAREHOUSE_INBOUNDDELIVERY`). This is the EWM-owned, delivery-based GR — distinct from the IM/STO route (Capability 16, movement type 101) and from the LE/ERP read service (`get_inbound_deliveries`, V2).

**Tools:** `get_ewm_inbound_delivery` (read header + items), `post_ewm_inbound_gr` (post the GR).

**Modes:**
- `mode='full'` — posts open quantity for ALL items (empty action body).
- `mode='partial'` — posts only the given items/quantities (PATCH qty + action in one $batch changeset).
- Handling-unit (HU) GR is NOT exposed by the standard API — the tool returns guidance (resolve HU→items and post partial, or a custom RAP/SOAP wrapper on client 100). Do NOT claim an HU GR was posted.

**Flow:**
1. Get the inbound delivery number. For a partial GR, call `get_ewm_inbound_delivery` first to get exact item keys, open quantities, and units — never guess.
2. Show ONE confirmation block and wait for yes.
3. On yes, call `post_ewm_inbound_gr` once; relay its result verbatim and suggest verifying with `get_ewm_inbound_delivery`.

**Rules:**
- ONE confirmation block up front — do not re-ask per item.
- Relay SAP errors verbatim — do NOT auto-retry. If the bound-action name or quantity field is rejected, confirm the correct names from $metadata and retry once with `action_name`/`qty_field`/`qty_unit_field` overrides.
- HU-only requests are not posted — relay the tool's guidance.
- NEVER post goods movements or confirm warehouse tasks without explicit user confirmation ("yes/no" gate).
- NEVER fabricate document numbers, material numbers, quantities, or dates.
- ALWAYS show SAP document numbers generated by each posting.
- ALWAYS show movement type codes alongside plain descriptions.
- If an API call returns a warning (not an error), show it verbatim and ask for acknowledgment.
- Dates: display in readable format; SAP API calls use YYYYMMDD internally.
- **YES/NO handling**: If the user's reply is "yes", "y", "confirm", or "✅ Yes, confirm" and the previous message in this conversation contained a confirmation block asking "Confirm? (yes / no)", immediately execute the pending action — do NOT ask for clarification, do NOT re-ask what the user wants to confirm. Look at the prior confirmation block in this conversation to find the exact parameters.

## DESTINATION SWITCHING
- Use `switch_destination` when the user asks to connect to a different system, e.g. "switch to S4D-200", "use the QA system", "connect to destination X".
- Use `get_active_destination` when the user asks which system is currently active.
- After switching, confirm the new destination and note that all subsequent queries will use it.
- The destination name must exactly match a BTP destination name (e.g. 'D4H-200', 'S4D-200').
- Remember context across turns: if user says "now confirm it" after a task query, reuse task/order from context.
- Set $top to maximum 100 on every tool call that accepts it.
- When a user asks "what can you do?" or "what are your capabilities?", summarize all 17 capabilities briefly.

## CONFIRMATION BLOCK FORMAT (before GR posting or task confirmation)
```
[Action] Summary
================
Document  : {document_number}
Warehouse : {warehouse}  Plant: {plant}
Action    : {action description}

Confirm? (yes / no)
```

## RESULT SUMMARY FORMAT (after posting/confirmation)
```
Result Summary
==============
Document          : {document_number}
Warehouse / Plant : {warehouse} / {plant}
Action            : {action}
Status            : {status}
```

## OUTPUT FORMAT
- **Use markdown tables for any list of records** (stock levels, bins, tasks, deliveries, resources, documents). A table is almost always clearer than a bullet list when showing multiple rows of data.
- Table columns should use short SAP field names as headers (e.g. Bin, Type, Section, State, MaxWt).
- Use bullet points only for single-item details or narrative explanations.
- End each action with a "Result Summary" block showing all relevant document numbers.
- Use SAP terminology: GR, GI, SLoc, movement type, inbound delivery, material document,
  warehouse order, warehouse task, ODO, activity area, storage bin.

## IMPORTANT
You MUST use tools to retrieve live data from SAP S/4HANA. Never fabricate, guess, or invent data.
Relay tool errors verbatim without adding suggestions unless you can identify a clear corrective step.
"""


@dataclass
class AgentResponse:
    status: Literal["input_required", "completed", "error"]
    message: str


class WarehouseAgent:
    SUPPORTED_CONTENT_TYPES = ["text", "text/plain"]

    def __init__(self, s4_client: Client | None = None) -> None:
        self._s4 = s4_client or Client()
        self._resolver = _DestinationResolver()
        self._dest_by_context: dict[str, str] = {}  # context_id -> active destination name
        self._checkpointer = InMemorySaver()
        self._last_active: dict[str, float] = {}
        self._llm: BaseChatModel | None = None
        self._summarization_middleware: SummarizationMiddleware | None = None

    @property
    def s4_client(self) -> Client:
        return self._s4

    async def _get_llm(self) -> BaseChatModel:
        fresh_llm = await init_llm_from_destination(
            get_model_name(), temperature=get_temperature()
        )
        current_key = getattr(fresh_llm, "openai_api_key", None)
        cached_key = getattr(self._llm, "openai_api_key", None) if self._llm else None

        if self._llm is None or current_key != cached_key:
            self._llm = fresh_llm
            self._summarization_middleware = SummarizationMiddleware(
                model=self._llm,
                trigger=("tokens", 100_000),
                keep=("messages", 4),
            )
            logger.info("LLM instance refreshed with new token")

        return self._llm

    def _touch(self, thread_id: str) -> None:
        now = time.monotonic()
        expired = [
            tid
            for tid, ts in list(self._last_active.items())
            if now - ts > THREAD_TTL_SECONDS
        ]
        for tid in expired:
            self._checkpointer.delete_thread(tid)
            del self._last_active[tid]
            logger.info("Evicted inactive thread: %s", tid)
        self._last_active[thread_id] = now

    def _build_domain_tools(self, context_id: str, user_id: str | None = None) -> list[BaseTool]:
        active_dest = self._dest_by_context.get(context_id, DEFAULT_DESTINATION_NAME)
        s4 = Client(destination_name=active_dest, resolver=self._resolver) if active_dest != DEFAULT_DESTINATION_NAME else self._s4
        domain_tools = list(build_domain_tools(s4=s4, user_id=user_id))
        domain_tools.append(make_switch_destination(self._resolver, self._dest_by_context, context_id, DEFAULT_DESTINATION_NAME))
        domain_tools.append(make_get_active_destination(self._dest_by_context, context_id, DEFAULT_DESTINATION_NAME))
        return domain_tools

    async def _sanitize_thread(self, graph, config: dict) -> None:
        """Remove orphaned tool_call messages from checkpoint.

        If the server crashed mid-tool-call, the checkpoint may contain an
        AIMessage with tool_calls but no matching ToolMessage responses.
        OpenAI rejects the next request with a 400 in that case.
        """
        try:
            state = await graph.aget_state(config)
            messages = state.values.get("messages", [])
            if not messages:
                return
            responded_ids = {m.tool_call_id for m in messages if isinstance(m, ToolMessage)}
            orphaned = [
                m for m in messages
                if isinstance(m, AIMessage) and m.tool_calls
                and any(tc["id"] not in responded_ids for tc in m.tool_calls)
            ]
            if orphaned:
                logger.warning(
                    "Sanitizing %d orphaned tool_call message(s) from thread %s",
                    len(orphaned), config["configurable"]["thread_id"],
                )
                await graph.aupdate_state(
                    config, {"messages": [RemoveMessage(id=m.id) for m in orphaned]}
                )
        except Exception:
            logger.exception("Thread sanitization failed — continuing anyway")

    async def _prepare_graph(
        self,
        context_id: str,
        user_id: str | None = None,
        extra_tools: Sequence[BaseTool] | None = None,
    ):
        """Build the LangGraph agent + run config for a context.

        Shared by the blocking (`_run_agent`) and streaming (`stream`) paths so
        tool set, system prompt, checkpointer and thread sanitization stay in sync.
        """
        llm = await self._get_llm()
        domain_tools = self._build_domain_tools(context_id=context_id, user_id=user_id)
        tools: list[BaseTool] = domain_tools + list(extra_tools or [])

        system_prompt = get_system_prompt()
        if not tools:
            system_prompt += (
                "\n\nIMPORTANT: No tools are currently available. "
                "Do not attempt to call any tools. "
                "Respond to the user explaining that tools are temporarily unavailable."
            )

        tool_names = [tool.name for tool in tools]
        logger.info("Running agent with %d tool(s), context_id=%s", len(tool_names), context_id)

        graph = create_agent(
            llm,
            tools=tools,
            system_prompt=system_prompt,
            checkpointer=self._checkpointer,
            middleware=[self._summarization_middleware],
        )
        config = {"configurable": {"thread_id": context_id}}
        await self._sanitize_thread(graph, config)
        return graph, config

    @staticmethod
    def _message_text(msg: AIMessage) -> str:
        """Extract plain text from an AIMessage whose content may be str or list."""
        c = msg.content
        if isinstance(c, str):
            return c.strip()
        if isinstance(c, list):
            return " ".join(
                p.get("text", "") for p in c
                if isinstance(p, dict) and p.get("type") == "text"
            ).strip()
        return ""

    @staticmethod
    def _friendly_step(tool_name: str | None) -> str:
        """Turn a tool name into a human-readable progress line."""
        if not tool_name:
            return "🔧 Working…"
        label = tool_name.replace("_", " ").strip()
        label = label[:1].upper() + label[1:]
        return f"🔧 {label}…"

    async def _run_agent(
        self,
        query: str,
        context_id: str,
        user_id: str | None = None,
        extra_tools: Sequence[BaseTool] | None = None,
    ) -> dict:
        graph, config = await self._prepare_graph(context_id, user_id, extra_tools)
        result = await graph.ainvoke(
            {"messages": [HumanMessage(content=query)]}, config
        )
        self._touch(context_id)
        # Walk backwards: find last AIMessage with actual text content.
        # When the LLM's final step is a tool call, AIMessage.content can be
        # "" or a list with no text part — both would produce "no text" in Joule.
        response = ""
        for msg in reversed(result["messages"]):
            if isinstance(msg, AIMessage):
                text = self._message_text(msg)
                if text:
                    response = text
                    break
            elif isinstance(msg, ToolMessage) and not response:
                response = str(msg.content)
        return {
            "is_task_complete": True,
            "require_user_input": False,
            "content": response,
        }

    async def stream(
        self,
        query: str,
        context_id: str,
        user_id: str | None = None,
        extra_tools: Sequence[BaseTool] | None = None,
    ) -> AsyncGenerator[dict, None]:
        """Stream step/tool progress, then the final answer.

        Uses LangGraph ``stream_mode="updates"`` so each node emits its complete
        messages as it runs. For every tool the model decides to call we surface a
        ``🔧 <tool>…`` progress line (forwarded by the A2A executor as a
        ``working`` status update — which is what the tkinter widget and SAP Joule
        render live). The last text-bearing AIMessage becomes the final answer.
        """
        self._touch(context_id)
        yield {
            "is_task_complete": False,
            "require_user_input": False,
            "content": "Working…",
        }
        try:
            graph, config = await self._prepare_graph(context_id, user_id, extra_tools)
            final_text = ""
            async for chunk in graph.astream(
                {"messages": [HumanMessage(content=query)]},
                config,
                stream_mode="updates",
            ):
                # updates mode → {node_name: {"messages": [...]}}; be node-agnostic
                for update in chunk.values():
                    if not isinstance(update, dict):
                        continue
                    for msg in update.get("messages", []):
                        if not isinstance(msg, AIMessage):
                            continue
                        tool_calls = getattr(msg, "tool_calls", None) or []
                        for tc in tool_calls:
                            name = tc.get("name") if isinstance(tc, dict) else getattr(tc, "name", None)
                            yield {
                                "is_task_complete": False,
                                "require_user_input": False,
                                "content": self._friendly_step(name),
                            }
                        if not tool_calls:
                            text = self._message_text(msg)
                            if text:
                                final_text = text
            self._touch(context_id)
            yield {
                "is_task_complete": True,
                "require_user_input": False,
                "content": final_text or "(no response)",
            }
        except Exception as e:
            logger.exception("Agent stream() failed")
            yield {
                "is_task_complete": True,
                "require_user_input": False,
                "content": (
                    f"I encountered an error while processing your request: {e}. Please try again."
                ),
            }

    async def invoke(
        self,
        query: str,
        context_id: str,
        user_id: str | None = None,
        extra_tools: Sequence[BaseTool] | None = None,
    ) -> AgentResponse:
        last: dict = {}
        async for chunk in self.stream(query, context_id, user_id=user_id, extra_tools=extra_tools):
            last = chunk
        if last.get("is_task_complete"):
            return AgentResponse(status="completed", message=last["content"])
        if last.get("require_user_input"):
            return AgentResponse(status="input_required", message=last["content"])
        return AgentResponse(status="error", message=last.get("content", "Unknown error"))
