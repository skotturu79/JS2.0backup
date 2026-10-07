"""
Test script for batch-expiry-risk-agent integration.

Tests Option 2: calling batch-expiry-risk-agent REST API as a tool
from qm-batch-transfer-agent before adding as a full skill.

Note: agent is in mock mode (PLANT_1001-1005 demo data).
      AM01/PROJVECTDEMO queries use the LLM /api/query endpoint which
      interprets results intelligently even when mock data doesn't match.

Usage:
    python test_expiry_risk.py
"""
import asyncio
import sys
import httpx

# Fix Windows console unicode
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = "https://batch-expiry-risk-agent-fantastic-parrot-mn.cfapps.us10.hana.ondemand.com"
TIMEOUT = 30.0

PASS = "PASS"
FAIL = "FAIL"
SEP = "-" * 70


def header(title):
    print(f"\n{'='*70}\n  {title}\n{'='*70}")


def section(name):
    print(f"\n{SEP}\n  {name}\n{SEP}")


async def query(question: str) -> dict:
    async with httpx.AsyncClient(timeout=TIMEOUT) as hc:
        r = await hc.post(f"{BASE}/api/query",
                          json={"question": question},
                          headers={"Content-Type": "application/json"})
    r.raise_for_status()
    return r.json()


async def scan() -> dict:
    async with httpx.AsyncClient(timeout=TIMEOUT) as hc:
        r = await hc.post(f"{BASE}/api/scan",
                          json={},
                          headers={"Content-Type": "application/json"})
    r.raise_for_status()
    return r.json()


async def get_scan_status(run_id: str) -> dict:
    async with httpx.AsyncClient(timeout=TIMEOUT) as hc:
        r = await hc.get(f"{BASE}/api/scan/{run_id}")
    r.raise_for_status()
    return r.json()


async def get_report(run_id: str) -> dict:
    async with httpx.AsyncClient(timeout=TIMEOUT) as hc:
        r = await hc.get(f"{BASE}/api/runs/{run_id}/report")
    r.raise_for_status()
    return r.json()


async def poll_scan(run_id: str, max_wait: int = 30) -> dict:
    for _ in range(max_wait):
        status = await get_scan_status(run_id)
        if status.get("status") == "completed":
            return status
        await asyncio.sleep(1)
    return {}


results = []


async def run_test(label, coro):
    print(f"\n>>  {label}")
    try:
        result = await coro
        if isinstance(result, str):
            lines = result.strip().splitlines()
        else:
            import json
            lines = json.dumps(result, indent=2).splitlines()
        for line in lines[:25]:
            print(f"   {line}")
        if len(lines) > 25:
            print(f"   ... ({len(lines)-25} more lines)")
        print(f"   {PASS}")
        results.append((label, True))
        return result
    except Exception as e:
        print(f"   {FAIL}: {e}")
        results.append((label, False))
        return None


async def main():

    # -----------------------------------------------------------------------
    header("TEST 1 — Check mock mode status")
    # -----------------------------------------------------------------------
    section("1a: Confirm agent is reachable and mock mode")

    async def check_mock():
        async with httpx.AsyncClient(timeout=TIMEOUT) as hc:
            r = await hc.get(f"{BASE}/api/config/mock-mode")
        return r.json()

    await run_test("GET /api/config/mock-mode", check_mock())

    # -----------------------------------------------------------------------
    header("TEST 2 — /api/query natural language questions")
    # -----------------------------------------------------------------------

    section("2a: Ask about PROJVECTDEMO at AM01 directly")
    r = await run_test(
        "query: expiry risk for PROJVECTDEMO batch DEMO01 at AM01",
        query("What is the expiry risk for batch DEMO01 of material PROJVECTDEMO at plant AM01?")
    )
    if r:
        print(f"\n   ANSWER PREVIEW:\n   {r.get('answer','')[:400]}")

    section("2b: Ask for all high-risk batches")
    r = await run_test(
        "query: show top high-risk batches",
        query("Show me the top 5 batches with highest expiry risk scores")
    )
    if r:
        print(f"\n   ANSWER PREVIEW:\n   {r.get('answer','')[:400]}")

    section("2c: Ask for redistribution recommendations")
    r = await run_test(
        "query: redistribution recommendations",
        query("Which batches need redistribution to avoid expiry?")
    )
    if r:
        print(f"\n   ANSWER PREVIEW:\n   {r.get('answer','')[:400]}")

    section("2d: Ask for disposal candidates")
    r = await run_test(
        "query: disposal candidates",
        query("Which batches are recommended for disposal or RTV?")
    )
    if r:
        print(f"\n   ANSWER PREVIEW:\n   {r.get('answer','')[:400]}")

    # -----------------------------------------------------------------------
    header("TEST 3 — /api/scan trigger and report")
    # -----------------------------------------------------------------------

    section("3a: Trigger a fresh scan")
    scan_result = await run_test("POST /api/scan", scan())

    if scan_result:
        run_id = scan_result.get("run_id", "")
        print(f"\n   run_id: {run_id}")

        section("3b: Poll scan until completed")

        async def poll():
            return await poll_scan(run_id)

        status = await run_test(f"poll scan {run_id[:8]}...", poll())

        if status:
            print(f"\n   Status: {status.get('status')}")
            print(f"   Recommendations: {status.get('recommendation_count')}")

            section("3c: Fetch scan report and parse recommendations")

            async def fetch_report():
                return await get_report(run_id)

            report = await run_test("GET /api/runs/{run_id}/report", fetch_report())

            if report:
                recs = report.get("recommendations", [])
                print(f"\n   Total recommendations: {len(recs)}")
                print(f"   Plants: {sorted(set(r.get('plant','') for r in recs))}")
                actions = {}
                for rec in recs:
                    a = rec.get("action_label", "Unknown")
                    actions[a] = actions.get(a, 0) + 1
                print(f"   Actions breakdown: {actions}")
                if recs:
                    top = sorted(recs, key=lambda x: x.get("risk_score", 0), reverse=True)[:3]
                    print(f"\n   Top 3 by risk score:")
                    for rec in top:
                        print(f"     Batch:{rec.get('batch_number')}  "
                              f"Mat:{rec.get('material_number')}  "
                              f"Plant:{rec.get('plant')}  "
                              f"Score:{rec.get('risk_score')}  "
                              f"Expiry:{rec.get('sled')}  "
                              f"Action:{rec.get('action_label')}")

    # -----------------------------------------------------------------------
    header("TEST 4 — Simulate what the tool will do in qm-batch-transfer-agent")
    # -----------------------------------------------------------------------

    section("4a: Combined — check stock then check expiry risk (cross-agent)")
    print("\n   Simulating: user asks 'Is batch DEMO01 of PROJVECTDEMO at risk of expiring?'")
    print("   Step 1: qm-batch-transfer-agent calls get_batch_stock → confirms stock exists")
    print("   Step 2: calls get_batch_expiry_risk → asks expiry agent about this batch")

    r = await run_test(
        "query: combined stock + expiry context question",
        query("I have batch DEMO01 of material PROJVECTDEMO at plant AM01 with 750 units unrestricted stock. "
              "Is this batch at expiry risk and what action do you recommend?")
    )
    if r:
        print(f"\n   ANSWER PREVIEW:\n   {r.get('answer','')[:600]}")

    # -----------------------------------------------------------------------
    header("SUMMARY")
    # -----------------------------------------------------------------------
    passed = sum(1 for _, v in results if v)
    failed = len(results) - passed
    print(f"\n  Total: {len(results)}   PASS: {passed}   FAIL: {failed}\n")
    for label, ok in results:
        print(f"  {'PASS' if ok else 'FAIL'}  {label}")
    print()
    return failed


if __name__ == "__main__":
    failed = asyncio.run(main())
    sys.exit(failed)
