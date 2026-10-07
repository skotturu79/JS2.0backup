"""
probe_z_apis.py — Probe custom Z OData V4 services on D4H-200
cf run-task warehouse-agent --command "python probe_z_apis.py" --name probe-z -w
"""
import asyncio, base64, json, os, re
import httpx

def _vcap(): return json.loads(os.environ.get("VCAP_SERVICES","{}"))
def _creds(l): return (_vcap().get(l) or [{}])[0].get("credentials",{})
DC = _creds("destination"); CC = _creds("connectivity")
DEST_URI=DC.get("uri",""); DEST_CID=DC.get("clientid",""); DEST_SEC=DC.get("clientsecret","")
CONN_URL=CC.get("token_service_url",""); CONN_CID=CC.get("clientid",""); CONN_SEC=CC.get("clientsecret","")
PH=CC.get("onpremise_proxy_host",""); PP=int(CC.get("onpremise_proxy_http_port",20003))
DEST=os.environ.get("S4HANA_DESTINATION_NAME","SBPA_d4hclnt200"); T=20.0

async def tok(c,url,cid,sec):
    r=await c.post(url.rstrip("/")+"/oauth/token",data={"grant_type":"client_credentials"},auth=(cid,sec),headers={"Accept":"application/json"})
    r.raise_for_status(); return r.json()["access_token"]

async def dest(dt):
    async with httpx.AsyncClient(timeout=T) as c:
        r=await c.get(f"{DEST_URI}/destination-configuration/v1/destinations/{DEST}",headers={"Authorization":f"Bearer {dt}","Accept":"application/json"})
    r.raise_for_status(); cfg=r.json().get("destinationConfiguration",{})
    return {"url":cfg.get("URL","").rstrip("/"),"user":cfg.get("User",""),"pw":cfg.get("Password",""),"client":cfg.get("sap-client","200")}

async def get(s4,path,pt,accept="application/json"):
    basic=base64.b64encode(f"{s4['user']}:{s4['pw']}".encode()).decode()
    try:
        async with httpx.AsyncClient(proxy=f"http://{PH}:{PP}",timeout=T) as c:
            r=await c.get(s4["url"]+path,headers={"Authorization":f"Basic {basic}","Proxy-Authorization":f"Bearer {pt}","Accept":accept,"sap-client":s4["client"]})
        return r.status_code,r.text
    except Exception as e: return 0,str(e)

def entity_sets(xml):
    return re.findall(r'<EntitySet[^>]+Name="([^"]+)"[^>]+EntityType="[^.]+\.([^"]+)"', xml)

def entity_types(xml):
    result = {}
    for m in re.finditer(r'<EntityType Name="([^"]+)"(.*?)</EntityType>', xml, re.DOTALL):
        name = m.group(1)
        keys = re.findall(r'<PropertyRef Name="([^"]+)"', m.group(2))
        props = re.findall(r'<Property Name="([^"]+)" Type="([^"]+)"', m.group(2))
        result[name] = {"keys": keys, "props": [(n, t.replace("Edm.","")) for n,t in props[:8]]}
    return result

Z_SERVICES = [
    "zui_ewmt_huld_lbl_o4",
    "zui_ewm_hu_number_o4",
    "zui_ewm_change_log_o4",
    "zui_ewm_scada_lift1_o4",
    "zui_ewm_scada_liftr_o4",
    "zui_mm_changelog",
    "zui_mm_mat_rfq",
    "zui_mm_qms_poemail_o4",
    "zui_mm_sup_quot_stat_o4",
    "zui_momaster_v4",
    "zui_scwmt_mnt_strts_o4",
    "zui_scwmt_prod_time_o4",
]

async def probe_service(s4, svc, pt):
    print(f"\n{'='*60}")
    print(f"Service: {svc.upper()}")
    print(f"{'='*60}")
    found = False
    for repo in ("srvd_a2x", "default", "odata"):
        # Try service definition = service group name, then strip _o4/_v4 suffix
        candidates = [svc, re.sub(r'_o4$|_v4$','',svc)]
        for sdef in candidates:
            path = f"/sap/opu/odata4/sap/{svc}/{repo}/sap/{sdef}/0001"
            st, body = await get(s4, path + "/$metadata", pt, accept="application/xml")
            if st == 200:
                print(f"  ✅ URL: {path}")
                ets = entity_sets(body)
                print(f"  EntitySets: {[e[0] for e in ets]}")
                etypes = entity_types(body)
                for ename, info in etypes.items():
                    print(f"  EntityType: {ename}  Keys: {info['keys']}")
                    for pn,pt2 in info["props"]:
                        print(f"    {pn} ({pt2})")
                # Sample first entity set
                if ets:
                    es_name = ets[0][0]
                    st2, data = await get(s4, path + f"/{es_name}?$top=3", pt)
                    print(f"\n  Sample {es_name} HTTP {st2}: {data[:600]}")
                found = True
                break
            elif st in (400, 403, 404, 503):
                print(f"  {repo}/{sdef}: HTTP {st}")
        if found:
            break
    if not found:
        print(f"  ❌ Not found on any URL pattern")

async def main():
    print("Z-API Probe — D4H-200 / PBAR")
    async with httpx.AsyncClient(timeout=T) as c:
        dt, ct = await asyncio.gather(
            tok(c, CONN_URL, DEST_CID, DEST_SEC),
            tok(c, CONN_URL, CONN_CID, CONN_SEC))
    s4 = await dest(dt)
    print(f"S4: {s4['url']}  client={s4['client']}\n")
    for svc in Z_SERVICES:
        await probe_service(s4, svc, ct)

if __name__ == "__main__":
    asyncio.run(main())
