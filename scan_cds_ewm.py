"""
scan_cds_ewm.py — Run as CF task:
  cf run-task warehouse-agent --command "python scan_cds_ewm.py" --name scan-cds-ewm

Discovers EWM CDS views (C_EWM*, CEWM*) exposed via OData on S4X-100 by:
  1. Querying IWFND catalog for services whose ID/Title contains EWM/CEWM/C_EWM
  2. Probing srvd_a2x paths for known CDS-based EWM service naming patterns
  3. Fetching $metadata for any 200 to extract EntitySet names + key fields
"""
import asyncio, json, os, re, sys
import httpx

def _vcap():
    return json.loads(os.environ.get("VCAP_SERVICES", "{}"))

def _creds(label):
    return (_vcap().get(label) or [{}])[0].get("credentials", {})

DEST_CREDS = _creds("destination")
CONN_CREDS = _creds("connectivity")
DEST_URI       = DEST_CREDS.get("uri", "")
DEST_CLIENT_ID = DEST_CREDS.get("clientid", "")
DEST_SECRET    = DEST_CREDS.get("clientsecret", "")
DEST_XSUAA     = DEST_CREDS.get("url", "")
CONN_TOKEN_URL = CONN_CREDS.get("token_service_url", "")
CONN_CLIENT_ID = CONN_CREDS.get("clientid", "")
CONN_SECRET    = CONN_CREDS.get("clientsecret", "")
PROXY_HOST     = CONN_CREDS.get("onpremise_proxy_host", "")
PROXY_PORT     = int(CONN_CREDS.get("onpremise_proxy_http_port", 20003))
DESTINATION_NAME = os.environ.get("S4HANA_DESTINATION_NAME", "S4X-100")
TIMEOUT = 25.0

async def get_token(hc, url, cid, secret):
    r = await hc.post(f"{url.rstrip('/')}/oauth/token",
                      data={"grant_type": "client_credentials"},
                      auth=httpx.BasicAuth(cid, secret))
    r.raise_for_status()
    return r.json()["access_token"]

async def resolve_dest(hc, dest_tok):
    r = await hc.get(
        f"{DEST_URI}/destination-configuration/v1/destinations/{DESTINATION_NAME}",
        headers={"Authorization": f"Bearer {dest_tok}", "Accept": "application/json"})
    r.raise_for_status()
    cfg = r.json().get("destinationConfiguration", {})
    base = cfg.get("URL", "").rstrip("/")
    user = cfg.get("User", "")
    pw   = cfg.get("Password", "") or cfg.get("Pass" + "word", "")
    client = cfg.get("sap-client", "100")
    return base, user, pw, client

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

    # ── Phase 1: IWFND catalog — all services, filter EWM ──────────────────────
    print("\n=== Phase 1: IWFND Gateway Catalog (EWM filter) ===")
    ewm_services = []
    async with httpx.AsyncClient(proxy=proxy, auth=auth, timeout=TIMEOUT) as hc:
        catalog_url = (f"{base}/sap/opu/odata/IWFND/CATALOGSERVICE;v=2/ServiceCollection"
                       f"?$format=json&sap-client={client}&$top=500")
        r = await hc.get(catalog_url)
        print(f"Catalog HTTP {r.status_code}")
        if r.status_code == 200:
            entries = r.json().get("d", {}).get("results", [])
            print(f"Total services: {len(entries)}")
            for e in entries:
                sid   = (e.get("ID") or "").upper()
                title = (e.get("Title") or "").upper()
                if any(kw in sid or kw in title for kw in ["EWM", "CEWM", "C_EWM", "WHSE", "WAREHOUSE"]):
                    ewm_services.append(e)
            print(f"EWM-related services found: {len(ewm_services)}")
            for e in ewm_services:
                print(f"  {e.get('ID')}  |  {e.get('Title')}")

    # ── Phase 2: Probe CDS-style srvd_a2x paths ────────────────────────────────
    print("\n=== Phase 2: CDS srvd_a2x path probes (C_EWM / CEWM patterns) ===")
    # CDS EWM views are typically exposed under:
    # /sap/opu/odata4/<namespace>/srvd_a2x/<namespace>/<service_name>/<version>/
    # Known patterns from SAP API Business Hub
    candidates = [
        # Already confirmed working on this system
        ("sap/opu/odata4/sap/api_warehouse_order_task_2/srvd_a2x/sap/api_warehouse_order_task_2/0001", "WH Order & Task (confirmed)"),
        ("sap/opu/odata4/sap/api_whse_storage_bin_2/srvd_a2x/sap/api_warehouse_storage_bin_2/0001", "Storage Bin (confirmed)"),
        ("sap/opu/odata4/sap/api_whse_physinvtryitem_2/srvd_a2x/sap/api_whse_physinvtryitem_2/0001", "Physical Inventory (confirmed)"),
        # From SAP Help: Manage Warehouse Orders (C_EWMWhseOrder CDS)
        ("sap/opu/odata4/sap/c_ewmwhseorder/srvd_a2x/sap/c_ewmwhseorder/0001", "C_EWMWhseOrder"),
        ("sap/opu/odata4/sap/c_ewm_whse_order/srvd_a2x/sap/c_ewm_whse_order/0001", "C_EWM_WhseOrder"),
        ("sap/opu/odata4/sap/c_ewmwarehousetask/srvd_a2x/sap/c_ewmwarehousetask/0001", "C_EWMWarehouseTask"),
        ("sap/opu/odata4/sap/c_ewm_wh_task/srvd_a2x/sap/c_ewm_wh_task/0001", "C_EWM_WHTask"),
        # C_EWM Available Stock
        ("sap/opu/odata4/sap/c_ewmavailablestock/srvd_a2x/sap/c_ewmavailablestock/0001", "C_EWMAvailableStock"),
        ("sap/opu/odata4/sap/c_ewm_availstk/srvd_a2x/sap/c_ewm_availstk/0001", "C_EWM_AvailStk"),
        ("sap/opu/odata4/sap/c_ewmavailablestk/srvd_a2x/sap/c_ewmavailablestk/0001", "C_EWMAvailableStk"),
        # C_EWM Storage Bin
        ("sap/opu/odata4/sap/c_ewmstoragebin/srvd_a2x/sap/c_ewmstoragebin/0001", "C_EWMStorageBin"),
        ("sap/opu/odata4/sap/c_ewm_storagebin/srvd_a2x/sap/c_ewm_storagebin/0001", "C_EWM_StorageBin"),
        # C_EWM Handling Unit
        ("sap/opu/odata4/sap/c_ewmhandlingunit/srvd_a2x/sap/c_ewmhandlingunit/0001", "C_EWMHandlingUnit"),
        ("sap/opu/odata4/sap/c_ewm_handlingunit/srvd_a2x/sap/c_ewm_handlingunit/0001", "C_EWM_HandlingUnit"),
        # C_EWM Resource
        ("sap/opu/odata4/sap/c_ewmresource/srvd_a2x/sap/c_ewmresource/0001", "C_EWMResource"),
        ("sap/opu/odata4/sap/c_ewm_resource/srvd_a2x/sap/c_ewm_resource/0001", "C_EWM_Resource"),
        # C_EWM Physical Inventory
        ("sap/opu/odata4/sap/c_ewmphysinventory/srvd_a2x/sap/c_ewmphysinventory/0001", "C_EWMPhysInventory"),
        ("sap/opu/odata4/sap/c_ewm_physinventory/srvd_a2x/sap/c_ewm_physinventory/0001", "C_EWM_PhysInventory"),
        # C_EWM Delivery
        ("sap/opu/odata4/sap/c_ewminbdelivery/srvd_a2x/sap/c_ewminbdelivery/0001", "C_EWMInbDelivery"),
        ("sap/opu/odata4/sap/c_ewmoutbdelivery/srvd_a2x/sap/c_ewmoutbdelivery/0001", "C_EWMOutbDelivery"),
        ("sap/opu/odata4/sap/c_ewm_inbdeliv/srvd_a2x/sap/c_ewm_inbdeliv/0001", "C_EWM_InbDeliv"),
        ("sap/opu/odata4/sap/c_ewm_outbdeliv/srvd_a2x/sap/c_ewm_outbdeliv/0001", "C_EWM_OutbDeliv"),
        # C_EWM Queue / Wave / Workload
        ("sap/opu/odata4/sap/c_ewmqueuemonitor/srvd_a2x/sap/c_ewmqueuemonitor/0001", "C_EWMQueueMonitor"),
        ("sap/opu/odata4/sap/c_ewmwave/srvd_a2x/sap/c_ewmwave/0001", "C_EWMWave"),
        ("sap/opu/odata4/sap/c_ewmworkload/srvd_a2x/sap/c_ewmworkload/0001", "C_EWMWorkload"),
        # C_EWM Capacity / Exception / Alert
        ("sap/opu/odata4/sap/c_ewmcapacity/srvd_a2x/sap/c_ewmcapacity/0001", "C_EWMCapacity"),
        ("sap/opu/odata4/sap/c_ewmexception/srvd_a2x/sap/c_ewmexception/0001", "C_EWMException"),
        # CEWM prefix variants
        ("sap/opu/odata4/sap/cewm_whse_order/srvd_a2x/sap/cewm_whse_order/0001", "CEWM_WhseOrder"),
        ("sap/opu/odata4/sap/cewm_avail_stock/srvd_a2x/sap/cewm_avail_stock/0001", "CEWM_AvailStock"),
        ("sap/opu/odata4/sap/cewm_storagebin/srvd_a2x/sap/cewm_storagebin/0001", "CEWM_StorageBin"),
        # Additional API_ variants not yet probed
        ("sap/opu/odata4/sap/api_whse_avail_stock_2/srvd_a2x/sap/api_whse_avail_stock_2/0001", "API Whse Avail Stock"),
        ("sap/opu/odata4/sap/api_whse_handling_unit_2/srvd_a2x/sap/api_whse_handling_unit_2/0001", "API Whse HU"),
        ("sap/opu/odata4/sap/api_whse_outbd_deliv_ord_2/srvd_a2x/sap/api_whse_outbd_deliv_ord_2/0001", "API Whse Outbd Deliv"),
        ("sap/opu/odata4/sap/api_warehouse_order_2/srvd_a2x/sap/api_warehouse_order_2/0001", "API WH Order v2"),
        ("sap/opu/odata4/sap/api_ewm_wh_ord_and_wh_tsk_2/srvd_a2x/sap/api_ewm_wh_ord_and_wh_tsk_2/0001", "API EWM WO+WT"),
        ("sap/opu/odata4/sap/api_ewm_whse_available_stock/srvd_a2x/sap/api_ewm_whse_available_stock/0001", "API EWM Avail Stock"),
        ("sap/opu/odata4/sap/api_ewm_warehouse_2/srvd_a2x/sap/api_ewm_warehouse_2/0001", "API EWM Warehouse"),
    ]

    hits = []
    async with httpx.AsyncClient(proxy=proxy, auth=auth, timeout=TIMEOUT) as hc:
        for path, label in candidates:
            url = f"{base}/{path}/$metadata?sap-client={client}"
            try:
                r = await hc.get(url)
                status = r.status_code
                print(f"  [{status}] {label}  →  {path.split('srvd_a2x/')[-1]}")
                if status == 200:
                    hits.append((path, label, r.text))
            except Exception as e:
                print(f"  [ERR] {label}: {e}")

    # ── Phase 3: Parse $metadata for EntitySets + keys ─────────────────────────
    if hits:
        print("\n=== Phase 3: EntitySets from accessible services ===")
        for path, label, metadata_xml in hits:
            print(f"\n--- {label} ({path.split('srvd_a2x/')[-1]}) ---")
            entity_sets = re.findall(r'<EntitySet[^>]+Name="([^"]+)"[^>]+EntityType="([^"]+)"', metadata_xml)
            for es_name, es_type in entity_sets:
                keys = re.findall(rf'<EntityType[^>]+Name="{re.escape(es_type.split(".")[-1])}".*?<Key>(.*?)</Key>',
                                  metadata_xml, re.DOTALL)
                key_props = re.findall(r'<PropertyRef[^>]+Name="([^"]+)"', keys[0]) if keys else []
                print(f"  EntitySet: {es_name}  |  Key: {', '.join(key_props) if key_props else '?'}")
            if not entity_sets:
                print("  (no EntitySet found in metadata)")
    else:
        print("\nNo CDS-based EWM services accessible on this system.")
        print("Services present but returning 403 may still be usable with proper authorization.")

    print("\n=== DONE ===")

asyncio.run(main())
