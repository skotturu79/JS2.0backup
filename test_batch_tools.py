"""
Batch tool unit tests — validates search_batches and get_batch_classification
output formatting with mock S4 responses using real D4H batch numbers
(confirmed via MCHA table: material 000000000001313326, plant STR1).

Note: API_BATCH_SRV must be activated on D4H/200 via /IWFND/MAINT_SERVICE
before live tests will pass.  These tests validate tool logic only.
"""
import asyncio
import sys

sys.path.insert(0, ".")

# ---------------------------------------------------------------------------
# Mock S4 client — returns realistic OData V2 responses
# ---------------------------------------------------------------------------

class MockS4Client:
    """Simulates the S4 client after LocalClient._unwrap() strips the outer 'd'."""

    def __init__(self, responses: dict):
        self._responses = responses  # path -> response body

    async def get(self, path, params=None, user_identity=None):
        # Return pre-canned response for matching path
        for key, val in self._responses.items():
            if key in path:
                return val
        return {"error": True, "message": f"No mock for {path}"}

    async def get_v4(self, path, params=None, user_identity=None):
        return await self.get(path, params, user_identity)


# ---------------------------------------------------------------------------
# Realistic mock data based on confirmed D4H/200 MCHA contents
# ---------------------------------------------------------------------------

BATCH_SEARCH_RESPONSE = {
    "results": [
        {
            "Material": "000000000001313326",
            "Plant": "STR1",
            "Batch": "0000000004",
            "BatchBySupplier": "",
            "MfgDate": "/Date(1672531200000)/",
            "ShlfLfExpirtnDt": None,
            "BestByDate": None,
            "CountryOfOrigin": "DE",
            "BatchAvailabilityType": "01",
            "IsMarkedForDeletion": False,
            "CreationDate": "/Date(1672531200000)/",
            "LastChangeDate": "/Date(1704067200000)/",
        },
        {
            "Material": "000000000001313326",
            "Plant": "STR1",
            "Batch": "0000000005",
            "BatchBySupplier": "SUP-BATCH-789",
            "MfgDate": "/Date(1680307200000)/",
            "ShlfLfExpirtnDt": "/Date(1735689600000)/",
            "BestByDate": None,
            "CountryOfOrigin": "DE",
            "BatchAvailabilityType": "01",
            "IsMarkedForDeletion": False,
            "CreationDate": "/Date(1680307200000)/",
            "LastChangeDate": "/Date(1704067200000)/",
        },
        {
            "Material": "000000000001313326",
            "Plant": "STR1",
            "Batch": "0000000006",
            "BatchBySupplier": "",
            "MfgDate": None,
            "ShlfLfExpirtnDt": None,
            "BestByDate": None,
            "CountryOfOrigin": "",
            "BatchAvailabilityType": "",
            "IsMarkedForDeletion": True,
            "CreationDate": "/Date(1700000000000)/",
            "LastChangeDate": "/Date(1700000000000)/",
        },
    ]
}

CLASSIFICATION_RESPONSE = {
    "results": [
        {
            "Material": "000000000001313326",
            "Plant": "STR1",
            "Batch": "0000000004",
            "Characteristic": "STORAGE_TEMP",
            "CharcValue": "AMBIENT",
            "CharcDecimalValue": "",
            "CharcValueUnit": "",
            "CharcFromDecimalValue": "",
            "CharcToDecimalValue": "",
        },
        {
            "Material": "000000000001313326",
            "Plant": "STR1",
            "Batch": "0000000004",
            "Characteristic": "NET_WEIGHT",
            "CharcValue": "",
            "CharcDecimalValue": "25.500",
            "CharcValueUnit": "KG",
            "CharcFromDecimalValue": "",
            "CharcToDecimalValue": "",
        },
        {
            "Material": "000000000001313326",
            "Plant": "STR1",
            "Batch": "0000000004",
            "Characteristic": "PURITY_PCT",
            "CharcValue": "",
            "CharcDecimalValue": "99.800",
            "CharcValueUnit": "%",
            "CharcFromDecimalValue": "99.500",
            "CharcToDecimalValue": "100.000",
        },
        {
            "Material": "000000000001313326",
            "Plant": "STR1",
            "Batch": "0000000004",
            "Characteristic": "LOT_NUMBER",
            "CharcValue": "LOT-2024-STR1-004",
            "CharcDecimalValue": "",
            "CharcValueUnit": "",
            "CharcFromDecimalValue": "",
            "CharcToDecimalValue": "",
        },
    ]
}

EMPTY_RESPONSE = {"results": []}


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

PASS = "\033[32mPASS\033[0m"
FAIL = "\033[31mFAIL\033[0m"
SEP = "-" * 70


async def run(label: str, coro):
    print(f"\n>> {label}")
    try:
        result = await coro
        for line in result.splitlines():
            print(f"   {line}")
        ok = "No batches found" not in result and "No classification" not in result
        print(f"   {PASS if ok else FAIL}")
        return ok
    except Exception as e:
        print(f"   {FAIL}: {e}")
        return False


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

async def test_search_batches_with_plant():
    """search_batches returns multi-batch list for material + plant."""
    from tools.batch_tools import make_search_batches
    s4 = MockS4Client({"A_Batch": BATCH_SEARCH_RESPONSE})
    tool = make_search_batches(s4)
    return await run(
        "search_batches(material=000000000001313326, plant=STR1)",
        tool.coroutine(material="000000000001313326", plant="STR1"),
    )


async def test_search_batches_all_plants():
    """search_batches with no plant filter shows (all plants) label."""
    from tools.batch_tools import make_search_batches
    s4 = MockS4Client({"A_Batch": BATCH_SEARCH_RESPONSE})
    tool = make_search_batches(s4)
    result = await tool.coroutine(material="000000000001313326")
    ok = "all plants" in result
    print(f"\n>> search_batches(material only) — expects '(all plants)' label")
    print(f"   {result.splitlines()[0]}")
    print(f"   {PASS if ok else FAIL}")
    return ok


async def test_search_batches_include_deleted():
    """include_deleted=True shows [MARKED FOR DELETION] batches."""
    from tools.batch_tools import make_search_batches
    s4 = MockS4Client({"A_Batch": BATCH_SEARCH_RESPONSE})
    tool = make_search_batches(s4)
    result = await tool.coroutine(material="000000000001313326", include_deleted=True)
    ok = "MARKED FOR DELETION" in result
    print(f"\n>> search_batches(include_deleted=True) — expects deletion marker")
    for line in result.splitlines():
        if "DELETION" in line or "Batches for" in line:
            print(f"   {line}")
    print(f"   {PASS if ok else FAIL}")
    return ok


async def test_search_batches_not_found():
    """Returns friendly message when no batches match."""
    from tools.batch_tools import make_search_batches
    s4 = MockS4Client({"A_Batch": EMPTY_RESPONSE})
    tool = make_search_batches(s4)
    result = await tool.coroutine(material="NONEXISTENT", plant="AM01")
    ok = "No batches found" in result and "NONEXISTENT" in result
    print(f"\n>> search_batches(no results) — expects friendly not-found message")
    print(f"   {result}")
    print(f"   {PASS if ok else FAIL}")
    return ok


async def test_get_batch_classification():
    """get_batch_classification returns all characteristics with values and units."""
    from tools.batch_tools import make_get_batch_classification
    s4 = MockS4Client({"A_BatchClassification": CLASSIFICATION_RESPONSE})
    tool = make_get_batch_classification(s4)
    return await run(
        "get_batch_classification(material=000000000001313326, plant=STR1, batch=0000000004)",
        tool.coroutine(
            material="000000000001313326",
            plant="STR1",
            batch="0000000004",
        ),
    )


async def test_get_batch_classification_not_found():
    """Returns friendly message when no characteristics exist."""
    from tools.batch_tools import make_get_batch_classification
    s4 = MockS4Client({"A_BatchClassification": EMPTY_RESPONSE})
    tool = make_get_batch_classification(s4)
    result = await tool.coroutine(
        material="000000000001313326", plant="STR1", batch="0000000099"
    )
    ok = "No classification" in result
    print(f"\n>> get_batch_classification(no results) — expects friendly not-found")
    print(f"   {result}")
    print(f"   {PASS if ok else FAIL}")
    return ok


async def main():
    print("=" * 70)
    print("  Batch Tool Tests — tool logic validation (mock S4 client)")
    print("  System: D4H/200 batch numbers (confirmed via MCHA table)")
    print("  Note: API_BATCH_SRV must be activated via /IWFND/MAINT_SERVICE")
    print("        before live OData tests can run.")
    print("=" * 70)

    results = await asyncio.gather(
        test_search_batches_with_plant(),
        test_search_batches_all_plants(),
        test_search_batches_include_deleted(),
        test_search_batches_not_found(),
        test_get_batch_classification(),
        test_get_batch_classification_not_found(),
    )

    total = len(results)
    passed = sum(results)
    print(f"\n{'='*70}")
    print(f"  Results: {passed}/{total} passed")
    print("=" * 70)

    # Also show live D4H test result (expected to fail until service activated)
    print("\n" + "=" * 70)
    print("  Live D4H/200 test (expected FAIL — service not yet activated)")
    print("=" * 70)
    import os
    if os.environ.get("S4_BASE"):
        import httpx
        import ssl

        # Re-use LocalClient pattern from test_skills.py
        S4_BASE = os.environ["S4_BASE"]
        S4_USER = os.environ.get("S4_USER", "sreddy03")
        S4_PASS = os.environ.get("S4_PASS", "")
        SAP_CLIENT = os.environ.get("SAP_CLIENT", "200")

        url = (
            f"{S4_BASE}/sap/opu/odata/sap/API_BATCH_SRV/A_Batch"
            f"?$filter=Material+eq+'000000000001313326'+and+Plant+eq+'STR1'"
            f"&$top=5&$format=json&sap-client={SAP_CLIENT}"
        )
        try:
            async with httpx.AsyncClient(verify=False, timeout=15) as hc:
                r = await hc.get(url, auth=httpx.BasicAuth(S4_USER, S4_PASS),
                                 headers={"Accept": "application/json"})
            print(f"\n  HTTP {r.status_code}")
            if r.status_code == 200:
                print(f"  SERVICE IS NOW ACTIVE — live data:")
                import json
                data = r.json().get("d", {}).get("results", [])
                for row in data[:5]:
                    print(f"    Batch={row.get('Batch')} Expiry={row.get('ShlfLfExpirtnDt')}")
            else:
                body = r.text[:200]
                print(f"  Expected error: {body}")
        except Exception as e:
            print(f"  Connection error: {e}")
    else:
        print("  Set S4_BASE / S4_USER / S4_PASS / SAP_CLIENT env vars for live test.")
        print("  Example:")
        print("    S4_BASE=https://10.254.2.59:44300 S4_USER=sreddy03 \\")
        print("    S4_PASS=<pw> SAP_CLIENT=200 python test_batch_tools.py")


if __name__ == "__main__":
    asyncio.run(main())
