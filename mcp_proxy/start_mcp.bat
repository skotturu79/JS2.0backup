@echo off
cd /d %~dp0
echo.
echo  Warehouse Agent MCP Proxy
echo  --------------------------
echo  MCP endpoint : http://localhost:8766/mcp
echo  Health check : http://localhost:8766/health
echo  Backend      : https://warehouse-agent.cfapps.us10-001.hana.ondemand.com/
echo.
echo  Register in Joule Desktop:
echo    Settings ^> MCP Servers ^> Add Server
echo    Name: Warehouse Agent
echo    URL : http://localhost:8766/mcp
echo.
py -m uvicorn warehouse_mcp:app --port 8766 --host 127.0.0.1
pause
