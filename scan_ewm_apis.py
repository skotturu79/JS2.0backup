"""
scan_ewm_apis.py  —  Run as CF task on warehouse-agent:
  cf run-task warehouse-agent "python scan_ewm_apis.py" --name scan-ewm

Scans ALL EWM/Warehouse OData services on S4X-100:
  1. Pulls full gateway catalog (ServiceGroups) and filters EWM keywords
  2. Tests each group's V4 srvd_a2x URL for HTTP 200
  3. On success, fetches $metadata and extracts EntitySet names
  4. Also probes a curated list of known SAP S/4HANA EWM API names
"""
import asyncio, json, os, re, sys, time
import httpx

# ── BTP service binding helpers ──────────────────────────────────────────────
def _vcap():
    raw = os.environ.get("VCAP_SERVICES", "{}")
    return json.loads(raw)

def _creds(label):
    return (_vcap().get(label) or [{}])[0].get("credentials", {})

DEST_CREDS = _creds("destination")
CONN_CREDS = _creds("connectivity")

DEST_URI       = DEST_CREDS.get("uri", "")
DEST_CLIENT_ID = DEST_CREDS.get("clientid", "")
DEST_SECRET    = DEST_CREDS.get("clientsecret", "")

CONN_TOKEN_URL = CONN_CREDS.get("token_service_url", "")
CONN_CLIENT_ID = CONN_CREDS.get("clientid", "")
CONN_SECRET    = CONN_CREDS.get("clientsecret", "")
PROXY_HOST     = CONN_CREDS.get("onpremise_proxy_host", "")
PROXY_PORT     = int(CONN_CREDS.get("onpremise_proxy_http_port", 20003))

DESTINATION_NAME = os.environ.get("S4HANA_DESTINATION_NAME", "S4X-100")
TIMEOUT = 20.0

# ── Token / destination resolution ───────────────────────────────────────────
async def get_token(client: httpx.AsyncClient, token_url: str, client_id: str, secret: str) -> str:
    r = await client.post(
        token_url.rstrip("/") + "/oauth/token",
        data={"grant_type": "client_credentials"},
        auth=(client_id, secret),
        headers={"Accept": "application/json"},
    )
    r.raise_for_status()
    return r.json()["access_token"]

async def resolve_destination(dest_token: str) -> dict:
    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        r = await c.get(
            f"{DEST_URI}/destination-configuration/v1/destinations/{DESTINATION_NAME}",
            headers={"Authorization": f"Bearer {dest_token}", "Accept": "application/json"},
        )
    r.raise_for_status()
    cfg = r.json().get("destinationConfiguration", {})
    return {
        "url":  cfg.get("URL", "").rstrip("/"),
        "user": cfg.get("User", ""),
        "pw":   cfg.get("Password", ""),
        "client": cfg.get("sap-client") or cfg.get("sap_client") or "100",
    }

# ── Proxy GET helper ──────────────────────────────────────────────────────────
async def proxy_get(s4: dict, path: str, proxy_token: str,
                    extra_headers: dict | None = None, accept: str = "application/json") -> tuple[int, str]:
    import base64
    basic = base64.b64encode(f"{s4['user']}:{s4['pw']}".encode()).decode()
    target_url = s4["url"] + path
    proxy_url  = f"http://{PROXY_HOST}:{PROXY_PORT}"

    headers = {
        "Authorization": f"Basic {basic}",
        "Proxy-Authorization": f"Bearer {proxy_token}",
        "Accept": accept,
        "sap-client": s4["client"],
    }
    if extra_headers:
        headers.update(extra_headers)

    try:
        async with httpx.AsyncClient(proxy=proxy_url, timeout=TIMEOUT) as c:
            r = await c.get(target_url, headers=headers)
        return r.status_code, r.text
    except Exception as e:
        return 0, str(e)

# ── EWM keyword filter ────────────────────────────────────────────────────────
EWM_KEYWORDS = [
    "ewm", "whse", "warehouse", "wm_", "_wm", "whstask", "whsord",
    "physinv", "storage_bin", "storagebin", "storagetype", "storagesection",
    "handlingunit", "handling_unit", "resource", "activity_area",
    "activityarea", "wave", "door", "yard", "staging", "putaway",
    "deconsolid", "packing", "label", "replenishment", "exception",
    "crossdock", "cross_dock", "kitting", "queuemonitor", "serialnumber",
    "serial_number", "inb_delivery", "inbound_del", "outb_delivery",
    "outbound_del", "transfer_order", "prod_supply", "capacity",
]

def is_ewm(grp: dict) -> bool:
    text = (
        (grp.get("ServiceGroupID") or grp.get("Id") or grp.get("Name") or "") + " " +
        (grp.get("Description") or "")
    ).lower()
    return any(kw in text for kw in EWM_KEYWORDS)

# ── Metadata entity set extraction ────────────────────────────────────────────
def extract_entity_sets(metadata_xml: str) -> list[str]:
    return re.findall(r'<EntitySet[^>]+Name="([^"]+)"', metadata_xml)

# ── Curated list of SAP EWM V4 service names to probe ────────────────────────
KNOWN_EWM_V4 = [
    # Already confirmed working (kept for baseline)
    "api_ewm_whse_available_stock",
    "api_ewm_wh_ord_and_wh_tsk_2",
    "api_whse_physinvtryitem_2",
    # Outbound/Inbound
    "api_whse_outb_delivery_ord_2",
    "api_whse_inb_delivery_2",
    "api_whse_inbd_delivery_order_2",
    # Handling Units
    "api_whse_handling_unit_2",
    "api_whse_hu_2",
    "api_whse_handlingunit_2",
    # Waves
    "api_whse_wave_2",
    "api_whse_waveprocessing_2",
    # Resources & Activity Areas
    "api_whse_resource_2",
    "api_whse_activity_area_2",
    "api_ewm_activityarea_2",
    # Storage master
    "api_ewm_whse_bin_2",
    "api_whse_storagebin_2",
    "api_whse_storage_bin_2",
    "api_whse_storage_type_2",
    "api_whse_storage_section_2",
    "api_whse_storagetype_2",
    "api_whse_storagesection_2",
    # Doors / Yards / Staging
    "api_whse_door_2",
    "api_whse_yard_2",
    "api_whse_staging_area_2",
    "api_whse_stagingarea_2",
    # Alerts / Exceptions
    "api_whse_alert_2",
    "api_whse_exception_2",
    # Replenishment
    "api_whse_replenishment_2",
    # Packing / Deconsolidation / Kitting
    "api_whse_packing_2",
    "api_whse_deconsolidation_2",
    "api_whse_kitting_2",
    # Cross-docking / Production supply
    "api_whse_cross_docking_2",
    "api_whse_prod_supply_2",
    "api_whse_prod_supplyelem_2",
    # Labels / Serial numbers / Queues
    "api_whse_label_2",
    "api_whse_serial_number_2",
    "api_whse_serialnumber_2",
    "api_whse_queue_monitor_2",
    "api_whse_queuemonitor_2",
    # Capacity
    "api_whse_capacity_consumpt_2",
    "api_whse_capacityconsumpt_2",
    # Stock
    "api_ewm_stock_2",
    "api_whse_stock_2",
    # Transfer orders (classic EWM term)
    "api_whse_transfer_order_2",
    "api_whse_transferorder_2",
    # Putaway rules
    "api_whse_putaway_rule_2",
    "api_whse_putawayrule_2",
    # Confirmations
    "api_whse_wh_task_confirm_2",
    "api_whse_taskkonfirmation_2",
]

async def probe_v4(s4: dict, svc_id: str, proxy_token: str) -> tuple[int, list[str], str]:
    """Try srvd_a2x and default repo types. Returns (status, entity_sets, working_path)."""
    for repo in ["srvd_a2x", "default"]:
        path = f"/sap/opu/odata4/sap/{svc_id}/{repo}/sap/{svc_id}/0001/"
        status, body = await proxy_get(s4, path, proxy_token)
        if status == 200:
            meta_path = f"/sap/opu/odata4/sap/{svc_id}/{repo}/sap/{svc_id}/0001/$metadata"
            _, meta_xml = await proxy_get(s4, meta_path, proxy_token, accept="application/xml")
            entities = extract_entity_sets(meta_xml)
            return status, entities, path
        if status not in (404, 0):
            return status, [], path
    return status, [], path  # last attempted path

# ── Main ──────────────────────────────────────────────────────────────────────
async def main():
    print("=" * 80)
    print("EWM / Warehouse OData API Scanner — S4X-100")
    print("=" * 80)

    if not all([DEST_URI, DEST_CLIENT_ID, DEST_SECRET, CONN_TOKEN_URL, CONN_CLIENT_ID, CONN_SECRET]):
        print("ERROR: Missing VCAP_SERVICES bindings. Run as CF task on warehouse-agent.")
        sys.exit(1)

    print("\nFetching tokens...")
    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        dest_token, conn_token = await asyncio.gather(
            get_token(c, CONN_TOKEN_URL, DEST_CLIENT_ID, DEST_SECRET),
            get_token(c, CONN_TOKEN_URL, CONN_CLIENT_ID, CONN_SECRET),
        )

    print("Resolving destination S4X-100...")
    s4 = await resolve_destination(dest_token)
    print(f"S4 Base: {s4['url']}  client={s4['client']}\n")

    # ── Step 1: Full catalog scan ─────────────────────────────────────────────
    print("Fetching gateway catalog...")
    status, body = await proxy_get(
        s4,
        "/sap/opu/odata4/iwfnd/config/default/iwfnd/catalog/0001/ServiceGroups?$top=1000",
        conn_token,
    )
    print(f"Catalog HTTP {status}")

    catalog_ewm = []
    if status == 200:
        try:
            all_groups = json.loads(body).get("value", [])
            catalog_ewm = [g for g in all_groups if is_ewm(g)]
            print(f"Total groups: {len(all_groups)}  |  EWM-related: {len(catalog_ewm)}\n")
        except Exception as e:
            print(f"Catalog parse error: {e}")
    else:
        print(f"Catalog error: {body[:300]}\n")

    # ── Step 2: Test catalog EWM groups ──────────────────────────────────────
    accessible, forbidden, missing, errors = [], [], [], []

    for grp in catalog_ewm:
        svc_id = (grp.get("ServiceGroupID") or grp.get("Id") or grp.get("Name") or "").lower()
        desc   = grp.get("Description", "")
        print(f"  catalog: {svc_id}...", end=" ", flush=True)
        status, entities, path = await probe_v4(s4, svc_id, conn_token)
        print(status)
        entry = {"id": svc_id, "desc": desc, "path": path, "entities": entities}
        if status == 200:   accessible.append(entry)
        elif status == 403: forbidden.append(entry)
        elif status == 404: missing.append(entry)
        else:               errors.append({**entry, "status": status})

    # ── Step 3: Probe curated known list (skip already tested) ───────────────
    tested = {e["id"] for e in accessible + forbidden + missing + errors}
    print(f"\nProbing {len(KNOWN_EWM_V4)} curated EWM V4 service names...")
    known_results = {"ok": [], "forbidden": [], "missing": [], "error": []}

    for svc_id in KNOWN_EWM_V4:
        if svc_id in tested:
            continue
        print(f"  known: {svc_id}...", end=" ", flush=True)
        status, entities, path = await probe_v4(s4, svc_id, conn_token)
        print("✅" if status == 200 else status)
        entry = {"id": svc_id, "path": path, "entities": entities}
        if status == 200:   known_results["ok"].append(entry)
        elif status == 403: known_results["forbidden"].append(entry)
        elif status == 404: known_results["missing"].append(entry)
        else:               known_results["error"].append({**entry, "status": status})

    # ── Step 4: Report ────────────────────────────────────────────────────────
    print("\n" + "=" * 80)
    print("RESULTS — ACCESSIBLE SERVICES (Ready to build tools)")
    print("=" * 80)

    all_accessible = accessible + known_results["ok"]
    for e in all_accessible:
        print(f"\n  ✅  {e['id']}")
        if e.get("desc"): print(f"      Desc    : {e['desc']}")
        print(f"      Path    : {e['path']}")
        if e["entities"]:
            print(f"      Entities: {', '.join(e['entities'])}")

    print("\n" + "=" * 80)
    print("RESULTS — 403 FORBIDDEN (Mapping/auth issue — needs Basis fix)")
    print("=" * 80)
    for e in forbidden + known_results["forbidden"]:
        print(f"  ⛔  {e['id']}  {e.get('desc','')}")

    print("\n" + "=" * 80)
    print("RESULTS — NOT FOUND (Not activated/published on this system)")
    print("=" * 80)
    for e in missing + known_results["missing"]:
        print(f"  ○   {e['id']}  {e.get('desc','')}")

    print("\n" + "=" * 80)
    total_ok = len(all_accessible)
    total_forbid = len(forbidden) + len(known_results["forbidden"])
    total_miss = len(missing) + len(known_results["missing"])
    print(f"SUMMARY: {total_ok} accessible  |  {total_forbid} forbidden  |  {total_miss} not found")
    print("=" * 80)

if __name__ == "__main__":
    asyncio.run(main())
