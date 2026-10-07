"""
probe_new_services.py — CF task to get full metadata for new services + crack HU path
cf run-task warehouse-agent --command "python probe_new_services.py" --name probe-new -w
"""
import asyncio, base64, json, os, re
import httpx

def _vcap(): return json.loads(os.environ.get("VCAP_SERVICES","{}"))
def _creds(l): return (_vcap().get(l) or [{}])[0].get("credentials",{})
DC = _creds("destination"); CC = _creds("connectivity")
DEST_URI=DC.get("uri",""); DEST_CID=DC.get("clientid",""); DEST_SEC=DC.get("clientsecret","")
CONN_URL=CC.get("token_service_url",""); CONN_CID=CC.get("clientid",""); CONN_SEC=CC.get("clientsecret","")
PH=CC.get("onpremise_proxy_host",""); PP=int(CC.get("onpremise_proxy_http_port",20003))
DEST=os.environ.get("S4HANA_DESTINATION_NAME","S4X-100"); T=20.0

async def tok(c,url,cid,sec):
    r=await c.post(url.rstrip("/")+"/oauth/token",data={"grant_type":"client_credentials"},auth=(cid,sec),headers={"Accept":"application/json"})
    r.raise_for_status(); return r.json()["access_token"]

async def dest(dt):
    async with httpx.AsyncClient(timeout=T) as c:
        r=await c.get(f"{DEST_URI}/destination-configuration/v1/destinations/{DEST}",headers={"Authorization":f"Bearer {dt}","Accept":"application/json"})
    r.raise_for_status(); cfg=r.json().get("destinationConfiguration",{})
    return {"url":cfg.get("URL","").rstrip("/"),"user":cfg.get("User",""),"pw":cfg.get("Password",""),"client":cfg.get("sap-client","100")}

async def get(s4,path,pt,accept="application/json"):
    basic=base64.b64encode(f"{s4['user']}:{s4['pw']}".encode()).decode()
    try:
        async with httpx.AsyncClient(proxy=f"http://{PH}:{PP}",timeout=T) as c:
            r=await c.get(s4["url"]+path,headers={"Authorization":f"Basic {basic}","Proxy-Authorization":f"Bearer {pt}","Accept":accept,"sap-client":s4["client"]})
        return r.status_code,r.text
    except Exception as e: return 0,str(e)

def parse_meta(xml):
    """Extract EntityType properties with types."""
    results = {}
    # Find all EntityTypes
    for et_match in re.finditer(r'<EntityType Name="([^"]+)"(.*?)</EntityType>', xml, re.DOTALL):
        et_name = et_match.group(1)
        et_body = et_match.group(2)
        props = re.findall(r'<Property Name="([^"]+)" Type="([^"]+)"', et_body)
        # Find key properties
        keys = re.findall(r'<PropertyRef Name="([^"]+)"', et_body)
        results[et_name] = {"keys": keys, "props": [(n,t.replace("Edm.","")) for n,t in props]}
    return results

def parse_entity_sets(xml):
    return re.findall(r'<EntitySet[^>]+Name="([^"]+)"[^>]+EntityType="[^.]+\.([^"]+)"', xml)

async def main():
    print("="*70)
    print("New Service Metadata Probe")
    print("="*70)

    async with httpx.AsyncClient(timeout=T) as c:
        dt,ct = await asyncio.gather(
            tok(c,CONN_URL,DEST_CID,DEST_SEC),
            tok(c,CONN_URL,CONN_CID,CONN_SEC))
    s4 = await dest(dt)
    print(f"S4: {s4['url']}\n")

    # ── 1. api_warehouse_2 ────────────────────────────────────────────────────
    print("="*70)
    print("1. API_WAREHOUSE_2  (Warehouse + WarehouseStorageType)")
    print("="*70)
    base = "/sap/opu/odata4/sap/api_warehouse_2/srvd_a2x/sap/api_warehouse_2/0001"
    st,xml = await get(s4, base+"/$metadata", ct, accept="application/xml")
    print(f"Metadata HTTP: {st}")
    if st==200:
        ets = parse_entity_sets(xml)
        print(f"EntitySets: {ets}")
        etypes = parse_meta(xml)
        for name,info in etypes.items():
            print(f"\n  EntityType: {name}")
            print(f"  Keys: {info['keys']}")
            print(f"  Properties:")
            for pn,pt in info["props"]:
                print(f"    {pn} ({pt})")
    # Sample data
    print("\n  --- Sample: Warehouse ---")
    st2,body = await get(s4, base+"/Warehouse?$top=5", ct)
    print(f"  HTTP {st2}: {body[:600]}")
    print("\n  --- Sample: WarehouseStorageType ---")
    st3,body = await get(s4, base+"/WarehouseStorageType?$top=5&$filter=EWMWarehouse eq '1710'", ct)
    print(f"  HTTP {st3}: {body[:800]}")

    # ── 2. api_warehouse_resource_2 ───────────────────────────────────────────
    print("\n"+"="*70)
    print("2. API_WAREHOUSE_RESOURCE_2  (WarehouseResource)")
    print("="*70)
    base2 = "/sap/opu/odata4/sap/api_warehouse_resource_2/srvd_a2x/sap/api_warehouse_resource_2/0001"
    st,xml = await get(s4, base2+"/$metadata", ct, accept="application/xml")
    print(f"Metadata HTTP: {st}")
    if st==200:
        ets = parse_entity_sets(xml)
        print(f"EntitySets: {ets}")
        etypes = parse_meta(xml)
        for name,info in etypes.items():
            print(f"\n  EntityType: {name}")
            print(f"  Keys: {info['keys']}")
            print(f"  Properties:")
            for pn,pt in info["props"]:
                print(f"    {pn} ({pt})")
    print("\n  --- Sample: WarehouseResource ---")
    st2,body = await get(s4, base2+"/WarehouseResource?$top=5&$filter=EWMWarehouse eq '1710'", ct)
    print(f"  HTTP {st2}: {body[:1000]}")
    print("\n  --- Sample: WhseResourceGroupQueueSqnc ---")
    st3,body = await get(s4, base2+"/WhseResourceGroupQueueSqnc?$top=5", ct)
    print(f"  HTTP {st3}: {body[:600]}")

    # ── 3. Crack API_HANDLINGUNIT path ─────────────────────────────────────────
    print("\n"+"="*70)
    print("3. API_HANDLINGUNIT — probing service ID variants")
    print("="*70)
    HU_CANDIDATES = [
        ("api_handlingunit","api_handlingunit"),
        ("api_handlingunit","api_handlingunit_2"),
        ("api_handlingunit","api_whse_handlingunit"),
        ("api_handlingunit","api_whse_handlingunit_2"),
        ("api_handlingunit","api_warehouse_handlingunit_2"),
        ("api_handlingunit","api_hu_2"),
        ("api_handlingunit","api_warehouse_hu_2"),
        ("api_handlingunit","api_whse_hu_2"),
        # Also try default repo type
    ]
    for grp,svc in HU_CANDIDATES:
        for repo in ("srvd_a2x","default"):
            path = f"/sap/opu/odata4/sap/{grp}/{repo}/sap/{svc}/0001/"
            st,body = await get(s4, path, ct)
            flag = "✅" if st==200 else ("⛔" if st==403 else "")
            print(f"  {grp}/{repo}/{svc}: {st} {flag}")
            if st==200:
                _,xml=await get(s4,path+"$metadata",ct,accept="application/xml")
                ets=parse_entity_sets(xml)
                print(f"    EntitySets: {ets}")

    # ── 4. Also probe ZSB_EWM_ORDER_ITEMS_HU to understand the HU link ────────
    print("\n"+"="*70)
    print("4. ZSB_EWM_ORDER_ITEMS_HU — custom EWM HU binding")
    print("="*70)
    for svc in ("zc_ewm_order_items_hu","zsb_ewm_order_items_hu","zc_ewm_orderitems_hu"):
        for repo in ("srvd_a2x","default"):
            path = f"/sap/opu/odata4/sap/zsb_ewm_order_items_hu/{repo}/sap/{svc}/0001/"
            st,_ = await get(s4, path, ct)
            print(f"  zsb_ewm_order_items_hu/{repo}/{svc}: {st}")

    # ── 5. ZSB_ODP_WHSEORDER ──────────────────────────────────────────────────
    print("\n"+"="*70)
    print("5. ZSB_ODP_WAREHOUSEORDER — custom WH order binding")
    print("="*70)
    for svc in ("zsb_odp_whseorder","zc_odp_warehouseorder","zc_odp_whseorder"):
        for repo in ("srvd_a2x","default","odata"):
            path = f"/sap/opu/odata4/sap/zsb_odp_whseorder/{repo}/sap/{svc}/0001/"
            st,_ = await get(s4, path, ct)
            print(f"  zsb_odp_whseorder/{repo}/{svc}: {st}")

if __name__=="__main__":
    asyncio.run(main())
