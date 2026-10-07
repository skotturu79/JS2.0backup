"""
SAP Logon Pad Crash Monitor
Collects crash logs from Windows Event Log, WER dumps, and SAP log files
whenever saplogon.exe crashes.
"""

import os
import sys
import time
import shutil
import subprocess
import threading
import datetime
import glob
import json
import traceback

# ── third-party (install if missing: pip install pywin32 psutil) ──────────────
try:
    import win32evtlog
    import win32evtlogutil
    import win32con
    import pywintypes
    HAS_WIN32 = True
except ImportError:
    HAS_WIN32 = False
    print("[WARN] pywin32 not installed — Event Log monitoring disabled.")
    print("       Run:  pip install pywin32")

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False
    print("[WARN] psutil not installed — process-exit watching disabled.")
    print("       Run:  pip install psutil")

# ── Configuration ─────────────────────────────────────────────────────────────
PROCESS_NAME   = "saplogon.exe"
POLL_INTERVAL  = 3          # seconds between process-alive polls
OUTPUT_DIR     = os.path.join(os.path.expanduser("~"), "SAP_CrashLogs")
MAX_EVENT_AGE  = 60 * 60    # look back 1 hour in Event Log on startup

# SAP Logon typical log directories (adjust if installed elsewhere)
SAP_LOG_DIRS = [
    os.path.join(os.environ.get("APPDATA", ""), "SAP", "Common"),
    os.path.join(os.environ.get("APPDATA", ""), "SAP"),
    r"C:\Program Files (x86)\SAP\FrontEnd\SAPgui",
    r"C:\Program Files\SAP\FrontEnd\SAPgui",
]
SAP_LOG_GLOBS = ["*.log", "*.trc", "*.txt", "SAPLOGON*", "dev_*"]

# Windows Error Reporting crash dump folders
WER_DIRS = [
    os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "Windows", "WER", "ReportArchive"),
    os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "Windows", "WER", "ReportQueue"),
    r"C:\ProgramData\Microsoft\Windows\WER\ReportArchive",
    r"C:\ProgramData\Microsoft\Windows\WER\ReportQueue",
]

# ── Helpers ───────────────────────────────────────────────────────────────────

def ts() -> str:
    return datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

def log(msg: str):
    print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {msg}")

def ensure_dir(path: str) -> str:
    os.makedirs(path, exist_ok=True)
    return path

def crash_dir() -> str:
    d = os.path.join(OUTPUT_DIR, f"crash_{ts()}")
    return ensure_dir(d)

# ── Event Log ─────────────────────────────────────────────────────────────────

def query_event_log(source: str, event_ids: list[int], since_seconds: int = MAX_EVENT_AGE) -> list[dict]:
    """Return matching Event Log entries as plain dicts."""
    if not HAS_WIN32:
        return []
    results = []
    cutoff = datetime.datetime.now() - datetime.timedelta(seconds=since_seconds)
    try:
        hand = win32evtlog.OpenEventLog(None, source)
        flags = win32evtlog.EVENTLOG_BACKWARDS_READ | win32evtlog.EVENTLOG_SEQUENTIAL_READ
        while True:
            events = win32evtlog.ReadEventLog(hand, flags, 0)
            if not events:
                break
            for ev in events:
                try:
                    gen_time = datetime.datetime.fromtimestamp(int(ev.TimeGenerated))
                except Exception:
                    continue
                if gen_time < cutoff:
                    break
                if ev.EventID & 0xFFFF in event_ids:
                    msg = ""
                    try:
                        msg = win32evtlogutil.SafeFormatMessage(ev, source)
                    except Exception:
                        msg = str(ev.StringInserts or "")
                    results.append({
                        "time":     gen_time.isoformat(),
                        "source":   source,
                        "event_id": ev.EventID & 0xFFFF,
                        "level":    ev.EventType,
                        "message":  msg,
                    })
        win32evtlog.CloseEventLog(hand)
    except pywintypes.error as e:
        log(f"  EventLog error ({source}): {e}")
    return results

def collect_event_logs(dest_dir: str):
    log("  Collecting Windows Event Log entries …")
    # Event IDs: 1000 = Application Error, 1001 = WER, 1026 = .NET crash
    app_events = query_event_log("Application", [1000, 1001, 1026])
    sys_events  = query_event_log("System",      [41, 6008])  # unexpected shutdown

    # Filter to SAP-related entries
    sap_events = [e for e in app_events
                  if "sap" in e["message"].lower() or "saplogon" in e["message"].lower()]
    all_events = sap_events + sys_events

    out_path = os.path.join(dest_dir, "event_log.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(all_events, f, indent=2, default=str)
    log(f"  → {len(all_events)} event log entries saved to {out_path}")

    # Also save a human-readable summary
    summary = os.path.join(dest_dir, "event_log_summary.txt")
    with open(summary, "w", encoding="utf-8") as f:
        for e in all_events:
            f.write(f"[{e['time']}] ID={e['event_id']}  {e['source']}\n")
            f.write(e["message"][:2000] + "\n---\n")

# ── SAP Log Files ─────────────────────────────────────────────────────────────

def collect_sap_logs(dest_dir: str):
    log("  Collecting SAP log files …")
    sap_dest = ensure_dir(os.path.join(dest_dir, "sap_logs"))
    copied = 0
    for d in SAP_LOG_DIRS:
        if not os.path.isdir(d):
            continue
        for pattern in SAP_LOG_GLOBS:
            for fpath in glob.glob(os.path.join(d, pattern)):
                if os.path.isfile(fpath):
                    try:
                        shutil.copy2(fpath, sap_dest)
                        copied += 1
                    except Exception as e:
                        log(f"    Could not copy {fpath}: {e}")
    log(f"  → {copied} SAP log file(s) copied to {sap_dest}")

# ── WER Crash Dumps ───────────────────────────────────────────────────────────

def collect_wer_reports(dest_dir: str):
    log("  Collecting WER crash reports …")
    wer_dest = ensure_dir(os.path.join(dest_dir, "wer_reports"))
    copied = 0
    cutoff = time.time() - MAX_EVENT_AGE * 4  # look back 4 hours for dumps
    for d in WER_DIRS:
        if not os.path.isdir(d):
            continue
        for entry in os.scandir(d):
            if not entry.is_dir():
                continue
            if "sap" not in entry.name.lower():
                continue
            if entry.stat().st_mtime < cutoff:
                continue
            try:
                dst = os.path.join(wer_dest, entry.name)
                shutil.copytree(entry.path, dst, dirs_exist_ok=True)
                copied += 1
            except Exception as e:
                log(f"    Could not copy WER report {entry.name}: {e}")
    log(f"  → {copied} WER report folder(s) copied to {wer_dest}")

# ── System Info ───────────────────────────────────────────────────────────────

def collect_system_info(dest_dir: str):
    log("  Collecting system info …")
    out_path = os.path.join(dest_dir, "system_info.txt")
    cmds = [
        ("OS Version",          "ver"),
        ("Installed SAP",       r'reg query "HKLM\SOFTWARE\SAP" /s'),
        ("Running Processes",   "tasklist"),
        ("Network Adapters",    "ipconfig /all"),
        ("Event Viewer Errors", 'wevtutil qe Application /c:20 /rd:true /f:text /q:"*[System[Provider[@Name=\'Application Error\'] and TimeCreated[timediff(@SystemTime) <= 3600000]]]"'),
    ]
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(f"Collected at: {datetime.datetime.now().isoformat()}\n\n")
        for title, cmd in cmds:
            f.write(f"{'='*60}\n{title}\n{'='*60}\n")
            try:
                result = subprocess.run(
                    cmd, shell=True, capture_output=True, text=True, timeout=15
                )
                f.write(result.stdout or "(no output)\n")
                if result.stderr:
                    f.write(f"[stderr] {result.stderr}\n")
            except Exception as e:
                f.write(f"Error: {e}\n")
            f.write("\n")
    log(f"  → System info saved to {out_path}")

# ── Full crash snapshot ───────────────────────────────────────────────────────

def take_crash_snapshot(reason: str = "manual"):
    d = crash_dir()
    log(f"\n{'='*60}")
    log(f"CRASH DETECTED ({reason})")
    log(f"Saving snapshot to: {d}")
    log(f"{'='*60}")

    # Write a manifest
    with open(os.path.join(d, "MANIFEST.txt"), "w") as f:
        f.write(f"SAP Logon Pad Crash Report\n")
        f.write(f"Captured:  {datetime.datetime.now().isoformat()}\n")
        f.write(f"Reason:    {reason}\n")
        f.write(f"Computer:  {os.environ.get('COMPUTERNAME','?')}\n")
        f.write(f"User:      {os.environ.get('USERNAME','?')}\n")

    collect_event_logs(d)
    collect_sap_logs(d)
    collect_wer_reports(d)
    collect_system_info(d)

    log(f"\nSnapshot complete → {d}\n")
    return d

# ── Process monitor ───────────────────────────────────────────────────────────

def find_saplogon_pid() -> int | None:
    if not HAS_PSUTIL:
        return None
    for proc in psutil.process_iter(["pid", "name"]):
        if proc.info["name"] and proc.info["name"].lower() == PROCESS_NAME:
            return proc.info["pid"]
    return None

def monitor_process():
    """Watch for saplogon.exe; capture a snapshot when it disappears unexpectedly."""
    log(f"Process monitor started (polling every {POLL_INTERVAL}s) …")
    pid = find_saplogon_pid()
    if pid:
        log(f"  {PROCESS_NAME} is running  (PID {pid})")
    else:
        log(f"  {PROCESS_NAME} is NOT running — will wait for it to start …")

    was_running = pid is not None

    while True:
        time.sleep(POLL_INTERVAL)
        pid = find_saplogon_pid()
        is_running = pid is not None

        if was_running and not is_running:
            # Process just vanished → likely a crash
            take_crash_snapshot(reason="saplogon.exe exited unexpectedly")
        elif not was_running and is_running:
            log(f"  {PROCESS_NAME} started (PID {pid})")

        was_running = is_running

# ── Event Log watcher ─────────────────────────────────────────────────────────

def monitor_event_log():
    """Poll the Application event log every 30 s for new crash events (ID 1000)."""
    if not HAS_WIN32:
        return
    log("Event Log monitor started …")
    seen_times = set()

    while True:
        time.sleep(30)
        events = query_event_log("Application", [1000], since_seconds=65)
        for ev in events:
            key = (ev["time"], ev["event_id"])
            if key in seen_times:
                continue
            seen_times.add(key)
            if "sap" in ev["message"].lower() or "saplogon" in ev["message"].lower():
                log(f"  [EventLog] Crash event detected at {ev['time']}")
                take_crash_snapshot(reason=f"Event ID 1000 at {ev['time']}")

# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    ensure_dir(OUTPUT_DIR)
    log(f"SAP Logon Pad Crash Monitor")
    log(f"Output directory: {OUTPUT_DIR}")
    log(f"Press Ctrl+C to stop.\n")

    if "--snapshot" in sys.argv:
        # Manual one-shot snapshot
        take_crash_snapshot(reason="manual --snapshot")
        return

    if not HAS_PSUTIL:
        log("[ERROR] psutil is required for process monitoring.")
        log("        pip install psutil pywin32")
        sys.exit(1)

    # Run both monitors in background threads
    threads = [
        threading.Thread(target=monitor_process,   daemon=True, name="proc-monitor"),
        threading.Thread(target=monitor_event_log, daemon=True, name="evtlog-monitor"),
    ]
    for t in threads:
        t.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        log("\nStopped.")

if __name__ == "__main__":
    main()
