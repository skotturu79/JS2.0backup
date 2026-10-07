"""
Local skill test — runs each warehouse tool directly against SAP S4X-100.
No LLM or BTP destination needed — calls OData via direct HTTP (same as curl tests).

Usage:
    python test_skills.py
"""
import asyncio
import os
import sys
from dataclasses import dataclass

import httpx

# ---------------------------------------------------------------------------
# Minimal S4HANA client for local testing (bypasses BTP destination resolver)
# ---------------------------------------------------------------------------

S4_BASE = os.environ.get("S4_BASE", "https://gclp0353.devint.net.sap:8443")
S4_USER = os.environ.get("S4_USER", "sudhakar")
S4_PASS = os.environ.get("S4_PASS", "Reddy@sudhakar1")
SAP_CLIENT = os.environ.get("SAP_CLIENT", "100")

# Demo values
MATERIAL  = "PROJVECTDEMO"
PLANT_SRC = "AM01"
PLANT_DST = "AM02"
SLOC_DST  = "171A"

# EWM demo values
EWM_PLANT    = "1710"
EWM_MATERIAL = "EWMS4-01"
EWM_WH       = "1710"


@dataclass
class _Dest:
    url: str
    auth_type: str = "BasicAuthentication"
    user: str = S4_USER
    pw: str = S4_PASS
    sap_client: str = SAP_CLIENT
    proxy_type: str = "Internet"
    additional: dict = None

    def __post_init__(self):
        if self.additional is None:
            self.additional = {}


class LocalClient:
    """Thin HTTP client that talks directly to SAP — no BTP plumbing."""

    def __init__(self):
        self._dest = _Dest(url=S4_BASE)

    async def destination(self):
        return self._dest

    def _auth(self, dest):
        return httpx.BasicAuth(dest.user, dest.pw)

    def _unwrap(self, body):
        if isinstance(body, dict) and "d" in body:
            return body["d"]
        return body

    async def _client_kwargs(self, dest):
        return {"timeout": 30.0}, {}

    async def get(self, service_path, params=None, user_identity=None):
        merged = dict(params or {})
        merged.setdefault("sap-client", SAP_CLIENT)
        url = f"{S4_BASE}{service_path}"
        # Build query string manually to avoid httpx percent-encoding the semicolon in service paths
        qs = "&".join(f"{k}={v}" for k, v in merged.items())
        full_url = f"{url}?{qs}"
        async with httpx.AsyncClient(timeout=30.0, verify=False) as hc:
            resp = await hc.get(full_url, auth=httpx.BasicAuth(S4_USER, S4_PASS),
                                headers={"Accept": "application/json"})
        if resp.status_code >= 400:
            return {"error": True, "status_code": resp.status_code, "message": resp.text}
        try:
            return self._unwrap(resp.json())
        except Exception:
            return {"error": True, "message": resp.text}

    async def get_v4(self, service_path, params=None, user_identity=None):
        merged = dict(params or {})
        merged.setdefault("sap-client", SAP_CLIENT)
        url = f"{S4_BASE}{service_path}"
        async with httpx.AsyncClient(timeout=30.0, verify=False) as hc:
            resp = await hc.get(url, auth=httpx.BasicAuth(S4_USER, S4_PASS),
                                params=merged,
                                headers={"Accept": "application/json;odata.metadata=minimal"})
        if resp.status_code >= 400:
            return {"error": True, "status_code": resp.status_code, "message": resp.text}
        try:
            body = resp.json()
            if isinstance(body, dict) and "value" in body:
                return body["value"]
            return body
        except Exception:
            return {"error": True, "message": resp.text}

    async def post_action_v4(self, service_path, body, service_root, user_identity=None):
        url = f"{S4_BASE}{service_path}"
        csrf_url = f"{S4_BASE}{service_root}"
        async with httpx.AsyncClient(timeout=30.0, verify=False) as hc:
            r0 = await hc.get(csrf_url, auth=httpx.BasicAuth(S4_USER, S4_PASS),
                              params={"sap-client": SAP_CLIENT},
                              headers={"x-csrf-token": "fetch", "Accept": "application/json"})
            csrf = r0.headers.get("x-csrf-token", "")
            resp = await hc.post(url, json=body,
                                 auth=httpx.BasicAuth(S4_USER, S4_PASS),
                                 params={"sap-client": SAP_CLIENT},
                                 headers={"x-csrf-token": csrf,
                                          "Content-Type": "application/json",
                                          "OData-Version": "4.0",
                                          "Accept": "application/json"})
        if resp.status_code >= 400:
            return {"error": True, "status_code": resp.status_code, "message": resp.text}
        if not resp.text.strip():
            return {"status_code": resp.status_code}
        try:
            return resp.json()
        except Exception:
            return {"status_code": resp.status_code, "raw": resp.text}

    async def post(self, service_path, body, service_root, user_identity=None):
        url = f"{S4_BASE}{service_path}"
        # Fetch CSRF token
        csrf_url = f"{S4_BASE}{service_root}"
        async with httpx.AsyncClient(timeout=30.0) as hc:
            r0 = await hc.get(csrf_url, auth=httpx.BasicAuth(S4_USER, S4_PASS),
                              params={"sap-client": SAP_CLIENT},
                              headers={"x-csrf-token": "fetch", "Accept": "application/json"})
            csrf = r0.headers.get("x-csrf-token", "")
            resp = await hc.post(url, json=body,
                                 auth=httpx.BasicAuth(S4_USER, S4_PASS),
                                 params={"sap-client": SAP_CLIENT},
                                 headers={"x-csrf-token": csrf,
                                          "Content-Type": "application/json",
                                          "Accept": "application/json"})
        if resp.status_code >= 400:
            return {"error": True, "status_code": resp.status_code, "message": resp.text}
        try:
            return resp.json()
        except Exception:
            return {"status_code": resp.status_code, "raw": resp.text}


# ---------------------------------------------------------------------------
# Test runner
# ---------------------------------------------------------------------------

PASS = "PASS"
FAIL = "FAIL"
SEP  = "-" * 70


def header(title):
    print(f"\n{'='*70}")
    print(f"  {title}")
    print('='*70)


def section(name):
    print(f"\n{SEP}")
    print(f"  {name}")
    print(SEP)


async def run_tool(label, coro):
    print(f"\n>>  {label}")
    try:
        result = await coro
        lines = result.strip().splitlines()
        for line in lines[:30]:
            print(f"   {line}")
        if len(lines) > 30:
            print(f"   ... ({len(lines) - 30} more lines)")
        print(f"   {PASS}")
        return True
    except Exception as e:
        print(f"   {FAIL}: {e}")
        return False


async def main():
    client = LocalClient()

    # Import tool factories
    sys.path.insert(0, ".")
    from tools.stock_tools import make_get_material_stock, make_get_stock_overview
    from tools.inbound_delivery_tools import (
        make_get_inbound_deliveries,
        make_get_inbound_delivery_detail,
        make_get_delivery_items,
        make_get_delivery_doc_flow,
    )
    from tools.goods_movement_tools import make_get_material_documents
    from tools.ewm_stock_tools import make_get_ewm_available_stock, make_get_ewm_physical_stock
    from tools.warehouse_order_tools import make_get_warehouse_orders, make_get_warehouse_tasks
    from tools.storage_bin_tools import make_get_storage_bins, make_get_fixed_bin_assignments
    from tools.ewm_outbound_tools import make_get_ewm_outbound_deliveries

    # Build tools
    get_stock       = make_get_material_stock(client)
    get_overview    = make_get_stock_overview(client)
    get_deliveries  = make_get_inbound_deliveries(client)
    get_del_detail  = make_get_inbound_delivery_detail(client)
    get_del_items   = make_get_delivery_items(client)
    get_doc_flow    = make_get_delivery_doc_flow(client)
    get_mat_docs    = make_get_material_documents(client)

    # EWM tools
    get_ewm_avail   = make_get_ewm_available_stock(client)
    get_ewm_phys    = make_get_ewm_physical_stock(client)
    get_wh_orders   = make_get_warehouse_orders(client)
    get_wh_tasks    = make_get_warehouse_tasks(client)
    get_bins        = make_get_storage_bins(client)
    get_fixbins     = make_get_fixed_bin_assignments(client)
    get_outbound    = make_get_ewm_outbound_deliveries(client)

    results = []

    # -----------------------------------------------------------------------
    header("SKILL 1 — warehouse-stock-skill")
    # -----------------------------------------------------------------------

    section("Test 1a: Stock for PROJVECTDEMO at AM02")
    r = await run_tool("get_material_stock(PROJVECTDEMO, AM02)",
                       get_stock.coroutine(material=MATERIAL, plant=PLANT_DST))
    results.append(("Skill1a: stock at AM02", r))

    section("Test 1b: Stock for PROJVECTDEMO at AM01")
    r = await run_tool("get_material_stock(PROJVECTDEMO, AM01)",
                       get_stock.coroutine(material=MATERIAL, plant=PLANT_SRC))
    results.append(("Skill1b: stock at AM01", r))

    section("Test 1c: Stock overview all plants PROJVECTDEMO")
    r = await run_tool("get_stock_overview(PROJVECTDEMO, all plants)",
                       get_overview.coroutine(material=MATERIAL, plant=""))
    results.append(("Skill1c: stock overview all plants", r))

    section("Test 1d: EWM plant 1710 stock (EWMS4-01)")
    r = await run_tool("get_material_stock(EWMS4-01, 1710)",
                       get_stock.coroutine(material=EWM_MATERIAL, plant=EWM_PLANT))
    results.append(("Skill1d: EWM plant 1710 stock", r))

    # -----------------------------------------------------------------------
    header("SKILL 2 — warehouse-inbound-delivery-skill")
    # -----------------------------------------------------------------------

    section("Test 2a: Inbound deliveries for plant AM02")
    r = await run_tool("get_inbound_deliveries(plant=AM02)",
                       get_deliveries.coroutine(plant=PLANT_DST, top=10))
    results.append(("Skill2a: deliveries for AM02", r))

    section("Test 2b: Inbound deliveries for EWM plant 1710")
    r = await run_tool("get_inbound_deliveries(plant=1710)",
                       get_deliveries.coroutine(plant=EWM_PLANT, top=10))
    results.append(("Skill2b: deliveries for 1710", r))

    section("Test 2c: All deliveries (no filter)")
    r = await run_tool("get_inbound_deliveries(no filter, top 5)",
                       get_deliveries.coroutine(plant="", top=5))
    results.append(("Skill2c: all deliveries", r))

    section("Test 2d: Delivery detail for 180001025")
    r = await run_tool("get_inbound_delivery_detail(180001025)",
                       get_del_detail.coroutine(delivery_document="180001025"))
    results.append(("Skill2d: delivery detail 180001025", r))

    section("Test 2e: Items for delivery 180001025")
    r = await run_tool("get_delivery_items(180001025)",
                       get_del_items.coroutine(delivery_document="180001025"))
    results.append(("Skill2e: items 180001025", r))

    section("Test 2f: Document flow for delivery 180001025")
    r = await run_tool("get_delivery_doc_flow(180001025)",
                       get_doc_flow.coroutine(delivery_document="180001025"))
    results.append(("Skill2f: doc flow 180001025", r))

    section("Test 2g: Items for EWM delivery 6000009 (open GR)")
    r = await run_tool("get_delivery_items(6000009)",
                       get_del_items.coroutine(delivery_document="6000009"))
    results.append(("Skill2g: items EWM 6000009", r))

    # -----------------------------------------------------------------------
    header("SKILL 3 — warehouse-goods-movement-skill")
    # -----------------------------------------------------------------------

    section("Test 3a: Material docs for PROJVECTDEMO at AM02")
    r = await run_tool("get_material_documents(PROJVECTDEMO, AM02)",
                       get_mat_docs.coroutine(material=MATERIAL, plant=PLANT_DST))
    results.append(("Skill3a: mat docs AM02", r))

    section("Test 3b: Material docs filtered by mvt 101 (GR)")
    r = await run_tool("get_material_documents(PROJVECTDEMO, AM02, mvt=101)",
                       get_mat_docs.coroutine(material=MATERIAL, plant=PLANT_DST,
                                              movement_type="101", top=5))
    results.append(("Skill3b: mat docs mvt 101", r))

    section("Test 3c: Material docs for PROJVECTDEMO batch DEMO01")
    r = await run_tool("get_material_documents(PROJVECTDEMO, AM02, batch=DEMO01)",
                       get_mat_docs.coroutine(material=MATERIAL, plant=PLANT_DST,
                                              batch="DEMO01", top=5))
    results.append(("Skill3c: mat docs batch DEMO01", r))

    section("Test 3d: Material docs for EWM plant 1710")
    r = await run_tool("get_material_documents(EWMS4-01, 1710)",
                       get_mat_docs.coroutine(material=EWM_MATERIAL, plant=EWM_PLANT, top=5))
    results.append(("Skill3d: mat docs EWM 1710", r))

    # -----------------------------------------------------------------------
    header("SKILL 4 — EWM V4 tools")
    # -----------------------------------------------------------------------

    section(f"Test 4a: EWM available stock WH={EWM_WH}")
    r = await run_tool(f"get_ewm_available_stock(ewm_warehouse={EWM_WH})",
                       get_ewm_avail.coroutine(ewm_warehouse=EWM_WH, top=10))
    results.append(("Skill4a: EWM available stock", r))

    section(f"Test 4b: EWM physical stock WH={EWM_WH}")
    r = await run_tool(f"get_ewm_physical_stock(ewm_warehouse={EWM_WH})",
                       get_ewm_phys.coroutine(ewm_warehouse=EWM_WH, top=10))
    results.append(("Skill4b: EWM physical stock", r))

    section(f"Test 4c: Warehouse orders WH={EWM_WH}")
    r = await run_tool(f"get_warehouse_orders(ewm_warehouse={EWM_WH})",
                       get_wh_orders.coroutine(ewm_warehouse=EWM_WH, top=10))
    results.append(("Skill4c: warehouse orders", r))

    section(f"Test 4d: Warehouse tasks WH={EWM_WH}")
    r = await run_tool(f"get_warehouse_tasks(ewm_warehouse={EWM_WH})",
                       get_wh_tasks.coroutine(ewm_warehouse=EWM_WH, top=10))
    results.append(("Skill4d: warehouse tasks", r))

    section(f"Test 4e: Storage bins WH={EWM_WH}")
    r = await run_tool(f"get_storage_bins(ewm_warehouse={EWM_WH})",
                       get_bins.coroutine(ewm_warehouse=EWM_WH, top=10))
    results.append(("Skill4e: storage bins", r))

    section(f"Test 4f: Fixed bin assignments WH={EWM_WH}")
    r = await run_tool(f"get_fixed_bin_assignments(ewm_warehouse={EWM_WH})",
                       get_fixbins.coroutine(ewm_warehouse=EWM_WH, top=10))
    results.append(("Skill4f: fixed bin assignments", r))

    section(f"Test 4g: EWM outbound deliveries WH={EWM_WH}")
    r = await run_tool(f"get_ewm_outbound_deliveries(ewm_warehouse={EWM_WH})",
                       get_outbound.coroutine(ewm_warehouse=EWM_WH, top=10))
    results.append(("Skill4g: EWM outbound deliveries", r))

    # -----------------------------------------------------------------------
    header("SUMMARY")
    # -----------------------------------------------------------------------
    passed = sum(1 for _, v in results if v)
    failed = len(results) - passed
    print(f"\n  Total: {len(results)}   {PASS}: {passed}   {FAIL}: {failed}\n")
    for label, ok in results:
        status = PASS if ok else FAIL
        print(f"  {status}  {label}")
    print()
    return failed


if __name__ == "__main__":
    failed = asyncio.run(main())
    sys.exit(failed)
