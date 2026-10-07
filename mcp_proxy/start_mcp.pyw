"""Silent background launcher — runs warehouse_mcp uvicorn without a terminal window."""
import subprocess, sys, os
os.chdir(os.path.dirname(os.path.abspath(__file__)))
subprocess.Popen(
    [sys.executable, "-m", "uvicorn", "warehouse_mcp:app",
     "--port", "8766", "--host", "127.0.0.1"],
    creationflags=0x08000000  # CREATE_NO_WINDOW on Windows
)
