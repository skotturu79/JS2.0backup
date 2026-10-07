"""
scan_ewm_v2.py  — Run as CF task: cf run-task warehouse-agent --command "python scan_ewm_v2.py" --name scan-ewm-v2 -w

Fixes from v1:
- Dumps raw catalog group fields to find correct field names
- Tests ALL actual service paths used by existing tools (as baselines)
- Probes catalog group IDs with both the group ID and stripped variants as service path
- Also tries the SAP API Business Hub canonical names for EWM
"""
import asyncio, json, os, re, sys
import httpx

# ── VCAP binding helpers ──────────────────────────────────────────────────────
def _vcap():
    return json.loads(os.environ.get("VCAP_SERVICES", "{}"))

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
DEST_NAME      = os.environ.get("S4HANA_DESTINATION_NAME", "S4X-100")
TIMEOUT        = 20.0

async def get_token(client, url, cid, secret):
    r = await client.post(url.rstrip("/") + "/oauth/token",
        data={"grant_type": "client_credentials"},
        auth=(cid, secret), headers={"Accept": "application/json"})
    r.raise_for_status()
    return r.json()["access_token"]

async def resolve_dest(dest_tok):
    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        r = await c.get(f"{DEST_URI}/destination-configuration/v1/destinations/{DEST_NAME}",
            headers={"Authorization": f"Bearer {dest_tok}", "Accept": "application/json"})
    r.raise_for_status()
    cfg = r.json().get("destinationConfiguration", {})
    return {"url": cfg.get("URL","").rstrip("/"), "user": cfg.get("User",""),
            "pw": cfg.get("Password",""), "client": cfg.get("sap-client","100")}

async def pget(s4, path, ptok, accept="application/json"):
    import base64
    basic = base64.b64encode(f"{s4['user']}:{s4['pw']}".encode()).decode()
    try:
        async with httpx.AsyncClient(
            proxy=f"http://{PROXY_HOST}:{PROXY_PORT}", timeout=TIMEOUT) as c:
            r = await c.get(s4["url"] + path, headers={
                "Authorization": f"Basic {basic}",
                "Proxy-Authorization": f"Bearer {ptok}",
                "Accept": accept, "sap-client": s4["client"]})
        return r.status_code, r.text
    except Exception as e:
        return 0, str(e)

def entities_from_meta(xml):
    return re.findall(r'<EntitySet[^>]+Name="([^"]+)"', xml)

def nav_from_meta(xml):
    return re.findall(r'<NavigationPropertyBinding[^>]+Target="([^"]+)"', xml)

async def probe(s4, grp_id, svc_id, ptok):
    """Try srvd_a2x then default repo. Returns (status, entities, annotations, path)."""
    for repo in ("srvd_a2x", "default"):
        path = f"/sap/opu/odata4/sap/{grp_id}/{repo}/sap/{svc_id}/0001/"
        st, body = await pget(s4, path, ptok)
        if st == 200:
            _, meta = await pget(s4, path + "$metadata", ptok, accept="application/xml")
            ents = entities_from_meta(meta)
            # Grab annotations: look for LabeledElement or Annotation Term
            labels = re.findall(r'Term="([^"]+)"', meta)[:10]
            return st, ents, labels, path
        if st not in (404, 0):
            return st, [], [], path
    return st, [], [], path

# ── Known-working baselines (actual paths from tools/*.py) ───────────────────
BASELINES = [
    # (group_id, service_id, description)
    ("api_whse_availablestock",      "api_whse_availablestock",        "EWM Available Stock"),
    ("api_whse_physstockprod",       "api_whse_physstockprod",         "EWM Physical Stock"),
    ("api_warehouse_order_task_2",   "api_warehouse_order_task_2",     "WH Order & Task"),
    ("api_warehouse_odo_2",          "api_whse_outb_delivery_order_2", "EWM Outbound Delivery"),
    ("api_whse_storage_bin_2",       "api_warehouse_storage_bin_2",    "Storage Bin"),
    ("api_whse_fixbin_assgnmnt",     "api_whse_fixbin_assgnmnt",       "Fixed Bin Assignment"),
    ("api_whse_physinvtryitem_2",    "api_whse_physinvtryitem_2",      "Physical Inventory"),
]

# ── SAP API Business Hub EWM V4 candidates with likely S4X naming pattern ────
# Pattern observed: group_id can differ from service_id
# e.g. group=api_warehouse_odo_2  service=api_whse_outb_delivery_order_2
CANDIDATES = [
    # Handling Units
    ("api_whse_handlingunit_2",      "api_whse_handlingunit_2",        "Handling Unit"),
    ("api_whse_hu_2",                "api_whse_hu_2",                  "Handling Unit (alt)"),
    ("api_warehouse_hu_2",           "api_whse_handlingunit_2",        "Handling Unit (wh prefix)"),
    ("api_whse_handlingunit_2",      "api_warehouse_handlingunit_2",   "Handling Unit (wh svc)"),
    # Waves
    ("api_whse_wave_2",              "api_whse_wave_2",                "Wave"),
    ("api_warehouse_wave_2",         "api_whse_wave_2",                "Wave (wh prefix)"),
    ("api_warehouse_wave_2",         "api_warehouse_wave_2",           "Wave (wh/wh)"),
    # Resources
    ("api_whse_resource_2",          "api_whse_resource_2",            "Warehouse Resource"),
    ("api_warehouse_resource_2",     "api_whse_resource_2",            "Warehouse Resource (wh)"),
    ("api_warehouse_resource_2",     "api_warehouse_resource_2",       "Warehouse Resource (wh/wh)"),
    # Activity Area
    ("api_whse_activity_area_2",     "api_whse_activity_area_2",       "Activity Area"),
    ("api_warehouse_activityarea_2", "api_whse_activity_area_2",       "Activity Area (wh)"),
    # Storage Bin master (try extra combos)
    ("api_whse_storage_bin_2",       "api_whse_storage_bin_2",         "Storage Bin (direct)"),
    ("api_warehouse_storage_bin_2",  "api_warehouse_storage_bin_2",    "Storage Bin (wh/wh)"),
    # Storage Type / Section
    ("api_whse_storagetype_2",       "api_whse_storagetype_2",         "Storage Type"),
    ("api_warehouse_storagetype_2",  "api_whse_storagetype_2",         "Storage Type (wh)"),
    ("api_whse_storagesection_2",    "api_whse_storagesection_2",      "Storage Section"),
    ("api_warehouse_storagesection_2","api_whse_storagesection_2",     "Storage Section (wh)"),
    # Doors / Staging / Yard
    ("api_whse_door_2",              "api_whse_door_2",                "Warehouse Door"),
    ("api_warehouse_door_2",         "api_whse_door_2",                "Warehouse Door (wh)"),
    ("api_whse_staging_area_2",      "api_whse_staging_area_2",        "Staging Area"),
    ("api_warehouse_stagingarea_2",  "api_whse_staging_area_2",        "Staging Area (wh)"),
    ("api_whse_yard_2",              "api_whse_yard_2",                "Yard"),
    ("api_warehouse_yard_2",         "api_whse_yard_2",                "Yard (wh)"),
    # Inbound Delivery
    ("api_whse_inb_delivery_2",      "api_whse_inb_delivery_2",        "EWM Inbound Delivery"),
    ("api_warehouse_inbdlv_2",       "api_whse_inb_delivery_2",        "EWM Inbound Delivery (wh)"),
    ("api_whse_inbd_dlv_ord_2",      "api_whse_inbd_dlv_ord_2",        "EWM Inbound Delivery Order"),
    # Replenishment
    ("api_whse_replenishment_2",     "api_whse_replenishment_2",       "Replenishment"),
    ("api_warehouse_replenishment_2","api_whse_replenishment_2",       "Replenishment (wh)"),
    # Packing
    ("api_whse_packing_2",           "api_whse_packing_2",             "Packing"),
    ("api_warehouse_packing_2",      "api_whse_packing_2",             "Packing (wh)"),
    # Deconsolidation
    ("api_whse_deconsolidation_2",   "api_whse_deconsolidation_2",     "Deconsolidation"),
    # Alerts / Exceptions
    ("api_whse_alert_2",             "api_whse_alert_2",               "Warehouse Alert"),
    ("api_warehouse_alert_2",        "api_whse_alert_2",               "Warehouse Alert (wh)"),
    ("api_whse_exception_2",         "api_whse_exception_2",           "Warehouse Exception"),
    # Production Supply
    ("api_whse_prod_supply_2",       "api_whse_prod_supply_2",         "Production Supply"),
    ("api_warehouse_prodsupply_2",   "api_whse_prod_supply_2",         "Production Supply (wh)"),
    # Serial Numbers
    ("api_whse_serialnumber_2",      "api_whse_serialnumber_2",        "Serial Number"),
    ("api_warehouse_serialnum_2",    "api_whse_serialnumber_2",        "Serial Number (wh)"),
    # Labels
    ("api_whse_label_2",             "api_whse_label_2",               "Warehouse Label"),
    ("api_warehouse_label_2",        "api_whse_label_2",               "Warehouse Label (wh)"),
    # Queue Monitor
    ("api_whse_queuemonitor_2",      "api_whse_queuemonitor_2",        "Queue Monitor"),
    # Capacity
    ("api_whse_capacity_2",          "api_whse_capacity_2",            "Capacity Consumption"),
    ("api_warehouse_capacity_2",     "api_whse_capacity_2",            "Capacity (wh)"),
    # Cross docking / kitting
    ("api_whse_crossdocking_2",      "api_whse_crossdocking_2",        "Cross Docking"),
    ("api_whse_kitting_2",           "api_whse_kitting_2",             "Kitting"),
    # EWM Stock (alternate names)
    ("api_whse_stock_2",             "api_whse_stock_2",               "Warehouse Stock"),
    ("api_ewm_stock_2",              "api_ewm_stock_2",                "EWM Stock"),
    # Task confirmation
    ("api_whse_taskkonfirmation_2",  "api_whse_taskkonfirmation_2",    "Task Confirmation"),
    ("api_warehouse_taskconfirm_2",  "api_whse_taskkonfirmation_2",    "Task Confirmation (wh)"),
    # Putaway
    ("api_whse_putaway_2",           "api_whse_putaway_2",             "Putaway"),
    ("api_warehouse_putaway_2",      "api_whse_putaway_2",             "Putaway (wh)"),
    # Transfer Order (classic EWM)
    ("api_whse_transferorder_2",     "api_whse_transferorder_2",       "Transfer Order"),
    ("api_warehouse_transferorder_2","api_whse_transferorder_2",       "Transfer Order (wh)"),
]

EWM_KEYWORDS = [
    "ewm","whse","warehouse","physinv","storage_bin","storagebin","storagetype",
    "storagesection","handlingunit","handling_unit","wave","door","yard",
    "staging","putaway","deconsolid","packing","label","replenishment",
    "exception","alert","crossdock","kitting","resource","activity_area",
    "activityarea","serial","transfer_order","prod_supply","capacity",
    "inbound_del","inb_del","outbound_del","outb_del","inbd","outbd",
]

def is_ewm(grp):
    text = " ".join(str(v) for v in grp.values()).lower()
    return any(kw in text for kw in EWM_KEYWORDS)

async def main():
    print("=" * 80)
    print("EWM API Scanner v2 — S4X-100")
    print("=" * 80)

    if not all([DEST_URI, DEST_SECRET, CONN_TOKEN_URL, CONN_SECRET]):
        print("ERROR: Missing VCAP_SERVICES. Run as CF task.")
        sys.exit(1)

    print("\nFetching tokens...")
    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        dest_tok, conn_tok = await asyncio.gather(
            get_token(c, CONN_TOKEN_URL, DEST_CLIENT_ID, DEST_SECRET),
            get_token(c, CONN_TOKEN_URL, CONN_CLIENT_ID, CONN_SECRET),
        )

    print("Resolving destination...")
    s4 = await resolve_dest(dest_tok)
    print(f"S4 URL: {s4['url']}  client={s4['client']}\n")

    # ── Step 0: Dump raw catalog sample to see field names ────────────────────
    print("Fetching catalog (first 5 groups to check field names)...")
    st, body = await pget(s4,
        "/sap/opu/odata4/iwfnd/config/default/iwfnd/catalog/0001/ServiceGroups?$top=5",
        conn_tok)
    if st == 200:
        sample = json.loads(body).get("value", [])
        if sample:
            print("  Field names in ServiceGroup:", list(sample[0].keys()))
            print("  Sample[0]:", json.dumps(sample[0], indent=4)[:400])

    # ── Step 1: Full catalog — get ALL EWM groups ─────────────────────────────
    print("\nFetching full catalog...")
    st, body = await pget(s4,
        "/sap/opu/odata4/iwfnd/config/default/iwfnd/catalog/0001/ServiceGroups?$top=500",
        conn_tok)
    all_groups, ewm_groups = [], []
    if st == 200:
        all_groups = json.loads(body).get("value", [])
        ewm_groups = [g for g in all_groups if is_ewm(g)]
        print(f"Total: {len(all_groups)}  EWM-related: {len(ewm_groups)}")
        print("\nEWM groups from catalog:")
        for g in ewm_groups:
            print(f"  {json.dumps(g)}")
    else:
        print(f"Catalog HTTP {st}: {body[:200]}")

    # ── Step 2: For each catalog EWM group, probe using all possible field values ──
    print("\n--- Probing catalog EWM groups ---")
    cat_ok, cat_forbidden, cat_miss = [], [], []
    for grp in ewm_groups:
        # Try every string value as a potential service ID / group ID
        ids = list({str(v).lower().strip() for v in grp.values()
                    if isinstance(v, str) and v.strip() and "/" not in v and len(v) < 80})
        desc = grp.get("Description") or grp.get("Title") or str(grp)
        found = False
        for gid in ids:
            for sid in ids:
                print(f"  {gid}/{sid}...", end=" ", flush=True)
                st, ents, _, path = await probe(s4, gid, sid, conn_tok)
                print(st)
                if st == 200:
                    cat_ok.append({"grp": gid, "svc": sid, "desc": desc,
                                   "path": path, "entities": ents})
                    found = True
                    break
                elif st == 403:
                    cat_forbidden.append({"grp": gid, "svc": sid, "desc": desc, "path": path})
            if found:
                break
        if not found:
            cat_miss.append({"desc": desc, "ids": ids})

    # ── Step 3: Baseline verification ────────────────────────────────────────
    print("\n--- Verifying baseline tool paths ---")
    baseline_ok, baseline_fail = [], []
    for grp_id, svc_id, desc in BASELINES:
        print(f"  {desc} ({grp_id}/{svc_id})...", end=" ", flush=True)
        st, ents, _, path = await probe(s4, grp_id, svc_id, conn_tok)
        print("✅" if st == 200 else st)
        entry = {"grp": grp_id, "svc": svc_id, "desc": desc, "path": path,
                 "entities": ents, "status": st}
        (baseline_ok if st == 200 else baseline_fail).append(entry)

    # ── Step 4: Probe candidate list ─────────────────────────────────────────
    print("\n--- Probing candidate EWM services ---")
    already_ok = {e["grp"] + "/" + e["svc"] for e in cat_ok + baseline_ok}
    cand_ok, cand_forbidden, cand_miss = [], [], []
    seen_cand = set()
    for grp_id, svc_id, desc in CANDIDATES:
        key = f"{grp_id}/{svc_id}"
        if key in already_ok or key in seen_cand:
            continue
        seen_cand.add(key)
        print(f"  {desc} ({grp_id}/{svc_id})...", end=" ", flush=True)
        st, ents, _, path = await probe(s4, grp_id, svc_id, conn_tok)
        print("✅" if st == 200 else st)
        entry = {"grp": grp_id, "svc": svc_id, "desc": desc, "path": path, "entities": ents}
        if st == 200:        cand_ok.append(entry)
        elif st == 403:      cand_forbidden.append(entry)
        else:                cand_miss.append(entry)

    # ── Report ────────────────────────────────────────────────────────────────
    print("\n" + "=" * 80)
    print("REPORT")
    print("=" * 80)

    print(f"\n✅ BASELINE WORKING ({len(baseline_ok)}) — existing tools confirmed OK")
    for e in baseline_ok:
        print(f"   {e['desc']}")
        print(f"   Path: {e['path']}")
        if e["entities"]: print(f"   Entities: {', '.join(e['entities'])}")

    if baseline_fail:
        print(f"\n❌ BASELINE BROKEN ({len(baseline_fail)}) — investigate!")
        for e in baseline_fail:
            print(f"   {e['desc']}  HTTP {e['status']}")

    all_new = cat_ok + cand_ok
    print(f"\n🆕 NEW ACCESSIBLE SERVICES ({len(all_new)}) — potential new tools")
    print("-" * 80)
    for e in all_new:
        print(f"\n   {e['desc']} ({e['grp']})")
        print(f"   Path    : {e['path']}")
        if e["entities"]: print(f"   Entities: {', '.join(e['entities'])}")

    all_forbidden = cat_forbidden + cand_forbidden
    print(f"\n⛔ FORBIDDEN 403 ({len(all_forbidden)}) — needs Basis fix")
    for e in all_forbidden:
        print(f"   {e.get('desc','')}  path: {e['path']}")

    print(f"\n○  CATALOG EWM GROUPS NOT RESOLVED ({len(cat_miss)})")
    for e in cat_miss:
        print(f"   {e['desc']}  ids={e['ids']}")

    print("\n" + "=" * 80)
    print(f"TOTAL NEW: {len(all_new)} accessible  |  {len(all_forbidden)} forbidden")
    print("=" * 80)

if __name__ == "__main__":
    asyncio.run(main())
