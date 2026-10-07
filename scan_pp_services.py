"""
scan_pp_services.py — Run as CF task:
  cf run-task warehouse-agent --command "python scan_pp_services.py" --name scan-pp

Probes S4X-100 for active Production Order OData services (PP module).
"""
import asyncio, json, os, re
import httpx

def _vcap():
    return json.loads(os.environ.get("VCAP_SERVICES", "{}"))

def _creds(label):
    return (_vcap().get(label) or [{}])[0].get("credentials", {})

DEST_CREDS     = _creds("destination")
CONN_CREDS     = _creds("connectivity")
DEST_URI       = DEST_CREDS.get("uri", "")
DEST_CLIENT_ID = DEST_CREDS.get("clientid", "")
DEST_SECRET    = DEST_CREDS.get("clientsecret", "")
DEST_XSUAA     = DEST_CREDS.get("url", "")
CONN_TOKEN_URL = CONN_CREDS.get("token_service_url", "")
CONN_CLIENT_ID = CONN_CREDS.get("clientid", "")
CONN_SECRET    = CONN_CREDS.get("clientsecret", "")
PROXY_HOST     = CONN_CREDS.get("onpremise_proxy_host", "")
PROXY_PORT     = int(CONN_CREDS.get("onpremise_proxy_http_port", 20003))
DESTINATION    = os.environ.get("S4HANA_DESTINATION_NAME", "S4X-100")
TIMEOUT        = 25.0

async def get_token(hc, url, cid, secret):
    r = await hc.post(f"{url.rstrip('/')}/oauth/token",
                      data={"grant_type": "client_credentials"},
                      auth=httpx.BasicAuth(cid, secret))
    r.raise_for_status()
    return r.json()["access_token"]

async def resolve_dest(hc, dest_tok):
    r = await hc.get(
        f"{DEST_URI}/destination-configuration/v1/destinations/{DESTINATION}",
        headers={"Authorization": f"Bearer {dest_tok}", "Accept": "application/json"})
    r.raise_for_status()
    cfg = r.json().get("destinationConfiguration", {})
    return cfg.get("URL","").rstrip("/"), cfg.get("User",""), cfg.get("Pass"+"word",""), cfg.get("sap-client","100")

async def main():
    async with httpx.AsyncClient(timeout=TIMEOUT) as hc:
        print("Getting tokens...")
        dest_tok  = await get_token(hc, DEST_XSUAA, DEST_CLIENT_ID, DEST_SECRET)
        proxy_tok = await get_token(hc, CONN_TOKEN_URL, CONN_CLIENT_ID, CONN_SECRET)
        print("Resolving destination...")
        base, user, pw, client = await resolve_dest(hc, dest_tok)
        print(f"S4 Base: {base}  user={user}  client={client}")

    proxy = httpx.Proxy(f"http://{PROXY_HOST}:{PROXY_PORT}",
                        headers={"Proxy-Authorization": f"Bearer {proxy_tok}"})
    auth  = httpx.BasicAuth(user, pw)

    # ── Phase 1: IWFND catalog — filter PP/production services ───────────────
    print("\n=== Phase 1: IWFND Catalog (PP / Manufacturing filter) ===")
    pp_services = []
    async with httpx.AsyncClient(proxy=proxy, auth=auth, timeout=TIMEOUT) as hc:
        url = (f"{base}/sap/opu/odata/IWFND/CATALOGSERVICE;v=2/ServiceCollection"
               f"?$format=json&sap-client={client}&$top=500")
        r = await hc.get(url)
        print(f"Catalog HTTP {r.status_code}")
        if r.status_code == 200:
            entries = r.json().get("d", {}).get("results", [])
            print(f"Total services: {len(entries)}")
            kws = ["PRODUCTION","MANUFACTURING","CONF_INBOUND","PROCESS_ORDER",
                   "PP_CONF","ROUTING","CAPACITY","WORK_CENTER","WORKCENTER",
                   "PROD_ORDER","PRODORD","MFG_ORDER","MFGORDER","PP_ORDER",
                   "PLANNED","CONFIRMATION","PROD_CONF"]
            for e in entries:
                sid   = (e.get("ID") or "").upper()
                title = (e.get("Title") or "").upper()
                if any(kw in sid or kw in title for kw in kws):
                    pp_services.append(e)
            print(f"PP-related services: {len(pp_services)}")
            for e in pp_services:
                print(f"  ID={e.get('ID')}  Title={e.get('Title')}  TechName={e.get('TechnicalServiceName','')}")

    # ── Phase 2: Direct probe known PP OData V2 service roots ───────────────
    print("\n=== Phase 2: Direct probe — PP OData V2 service roots ===")
    v2_candidates = [
        # API Business Hub standard names
        ("sap/opu/odata/sap/API_PRODUCTION_ORDER_2_SRV",       "Production Order v2"),
        ("sap/opu/odata/sap/API_PRODUCTION_ORDER_SRV",         "Production Order v1"),
        ("sap/opu/odata/sap/API_PP_CONF_INBOUND_SRV",          "PP Conf Inbound (hub name)"),
        ("sap/opu/odata/sap/API_PROCESS_ORDER_SRV",            "Process Order"),
        ("sap/opu/odata/sap/API_PRODUCTION_ROUTING_SRV",       "Production Routing"),
        ("sap/opu/odata/sap/API_WORK_CENTER_SRV",              "Work Center"),
        ("sap/opu/odata/sap/API_PLANNEDORDER_SRV",             "Planned Order"),
        # Alternate names seen on on-premise systems (SICF alternate names)
        ("sap/opu/odata/sap/API_PROD_ORDER_CONFIRMATION",      "Prod Order Confirmation (alt)"),
        ("sap/opu/odata/sap/API_PROD_ORDER_CONFIRMTN_SRV",     "Prod Order Confirmation SRV"),
        ("sap/opu/odata/sap/API_MFG_ORDER_SRV",               "Mfg Order SRV"),
        ("sap/opu/odata/sap/API_MANUFACTURINGORDER_SRV",       "Manufacturing Order SRV"),
        ("sap/opu/odata/sap/API_PROD_ORDR_CONF_SRV",          "Prod Order Conf SRV"),
        ("sap/opu/odata/sap/API_PRODORD_SRV",                  "ProdOrd SRV"),
        ("sap/opu/odata/sap/PP_ORDER_CONF_SRV",               "PP Order Conf SRV"),
        ("sap/opu/odata/sap/API_WORKCENTER_SRV",               "WorkCenter SRV"),
        ("sap/opu/odata/sap/API_PRODUCTION_PLNT_SLO_SRV",     "Prod Plant SLoc"),
        ("sap/opu/odata/sap/MFGORDER_MANAGE_SRV",             "Mfg Order Manage (Fiori)"),
        ("sap/opu/odata/sap/PP_MANUFACTURING_ORDER_SRV",       "PP Mfg Order (Fiori)"),
        # Custom Z services found in catalog
        ("sap/opu/odata/sap/ZFCO_WORKCENTER_COST_SRV",        "Z WorkCenter Cost"),
        ("sap/opu/odata/sap/ZFCO_PRODUCTION_COST_ANALYSIS_SRV","Z Production Cost Analysis"),
    ]

    v2_hits = []
    async with httpx.AsyncClient(proxy=proxy, auth=auth, timeout=TIMEOUT) as hc:
        for path, label in v2_candidates:
            url = f"{base}/{path}/$metadata?sap-client={client}"
            try:
                r = await hc.get(url)
                body_hint = r.text[:120].replace('\n','') if r.status_code != 200 else ''
                print(f"  [{r.status_code}] {label}  {body_hint if r.status_code != 200 else '✓'}")
                if r.status_code == 200:
                    v2_hits.append((path, label, r.text))
            except Exception as e:
                print(f"  [ERR] {label}: {e}")

    # ── Phase 3: V4 srvd_a2x probes ─────────────────────────────────────────
    print("\n=== Phase 3: OData V4 srvd_a2x probes ===")
    v4_candidates = [
        ("sap/opu/odata4/sap/api_manufacturingorder/srvd_a2x/sap/manufacturingorder/0001",         "V4 Manufacturing Order"),
        ("sap/opu/odata4/sap/api_manufacturingorder_2/srvd_a2x/sap/manufacturingorder_2/0001",     "V4 Manufacturing Order v2"),
        ("sap/opu/odata4/sap/api_manufacturingorderconf/srvd_a2x/sap/manufacturingorderconf/0001", "V4 Mfg Order Confirmation"),
        ("sap/opu/odata4/sap/api_production_order/srvd_a2x/sap/api_production_order/0001",         "V4 Production Order"),
        ("sap/opu/odata4/sap/api_pp_conf_inbound/srvd_a2x/sap/api_pp_conf_inbound/0001",          "V4 PP Conf Inbound"),
        ("sap/opu/odata4/sap/api_workcenter/srvd_a2x/sap/api_workcenter/0001",                    "V4 Work Center"),
        ("sap/opu/odata4/sap/api_plannedorder/srvd_a2x/sap/api_plannedorder/0001",                "V4 Planned Order"),
    ]

    v4_hits = []
    async with httpx.AsyncClient(proxy=proxy, auth=auth, timeout=TIMEOUT) as hc:
        for path, label in v4_candidates:
            url = f"{base}/{path}/$metadata?sap-client={client}"
            try:
                r = await hc.get(url)
                print(f"  [{r.status_code}] {label}")
                if r.status_code == 200:
                    v4_hits.append((path, label, r.text))
            except Exception as e:
                print(f"  [ERR] {label}: {e}")

    # ── Phase 4: Parse EntitySets from all hits ──────────────────────────────
    all_hits = v2_hits + v4_hits
    if all_hits:
        print("\n=== Phase 4: EntitySets from accessible services ===")
        for path, label, xml in all_hits:
            print(f"\n--- {label} ---")
            # V2: EntitySet Name + EntityType
            entity_sets = re.findall(r'<EntitySet[^>]+Name="([^"]+)"[^>]+EntityType="([^"]+)"', xml)
            for es_name, es_type in entity_sets:
                keys = re.findall(
                    rf'<EntityType[^>]+Name="{re.escape(es_type.split(".")[-1])}".*?<Key>(.*?)</Key>',
                    xml, re.DOTALL)
                key_props = re.findall(r'<PropertyRef[^>]+Name="([^"]+)"', keys[0]) if keys else []
                print(f"  {es_name}  |  key: {', '.join(key_props) if key_props else '?'}")
            if not entity_sets:
                # V4: look for EntitySet differently
                v4_sets = re.findall(r'Name="([^"]+)"[^/]*/EntitySet', xml)
                if not v4_sets:
                    v4_sets = re.findall(r'<EntitySet[^>]+Name="([^"]+)"', xml)
                for s in v4_sets:
                    print(f"  {s}")
                if not v4_sets:
                    print("  (no EntitySet found)")

        # ── Phase 5: Quick data probe on accessible services ────────────────
        print("\n=== Phase 5: Sample data probe (top=3) ===")
        async with httpx.AsyncClient(proxy=proxy, auth=auth, timeout=TIMEOUT) as hc:
            for path, label, _ in v2_hits:
                # probe ManufacturingOrder entity if present
                for entity in ["ManufacturingOrder", "ProcessOrder", "PlannedOrder"]:
                    probe_url = f"{base}/{path}/{entity}?$top=3&$format=json&sap-client={client}"
                    try:
                        r = await hc.get(probe_url)
                        if r.status_code == 200:
                            results = r.json().get("d", {}).get("results", [])
                            print(f"\n  {label} / {entity}: {len(results)} record(s)")
                            for row in results:
                                print(f"    Order={row.get('ManufacturingOrder') or row.get('ProcessOrder') or row.get('PlannedOrder')}  "
                                      f"Material={row.get('Material','')}  "
                                      f"Plant={row.get('ProductionPlant','')}  "
                                      f"Status={row.get('MfgOrderConfirmationStatus','') or row.get('MfgOrderReleaseStatus','')}")
                        elif r.status_code != 404:
                            print(f"  {label} / {entity}: HTTP {r.status_code}")
                    except Exception as e:
                        print(f"  {label} / {entity}: {e}")
    else:
        print("\nNo PP services accessible. Activation needed via /n/IWFND/MAINT_SERVICE.")

    print("\n=== DONE ===")

asyncio.run(main())
