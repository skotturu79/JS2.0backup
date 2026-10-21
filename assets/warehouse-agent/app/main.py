import os

if os.environ.get("JOULE_RUNTIME"):
    try:
        from sap_cloud_sdk.aicore import set_aicore_config
        from sap_cloud_sdk.core.telemetry import auto_instrument
        set_aicore_config()
        auto_instrument()
    except ImportError:
        pass

import logging

import click
import uvicorn
from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import AgentCapabilities, AgentCard, AgentSkill
from starlette.middleware.base import BaseHTTPMiddleware

from agent_executor import AgentExecutor
from mcp_tools import set_user_token

try:
    from opentelemetry.instrumentation.starlette import StarletteInstrumentor
    _STARLETTE_INSTRUMENTED = True
except ImportError:
    _STARLETTE_INSTRUMENTED = False
    StarletteInstrumentor = None

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "8080"))


def _extract_jwt(auth_hdr: str) -> "str | None":
    segs = auth_hdr.split()
    if len(segs) == 2 and segs[0].lower() == "bearer":
        return segs[-1]
    return None


class JWTContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        ctx_tok = _extract_jwt(request.headers.get("authorization", ""))
        set_user_token(ctx_tok)
        try:
            response = await call_next(request)
            return response
        finally:
            set_user_token(None)


@click.command()
@click.option("--host", default=HOST)
@click.option("--port", default=PORT)
def main(host: str, port: int):
    skill = AgentSkill(
        id="warehouse-agent",
        name="warehouse-agent",
        description=(
            "AI Agent for SAP S/4HANA Warehousing and Production — "
            "EWM stock, warehouse orders, inbound/outbound deliveries, "
            "production order tracking, component availability, and goods movements"
        ),
        tags=["warehouse", "stock", "delivery", "goods-receipt", "production", "ewm", "pp", "sto", "transfer"],
        examples=[
            "List released production orders for plant BAR1",
            "Show details for production order 1001176",
            "Show components for production order 1001176",
            "Show operations for production order 1001176",
            "What is the status of production order 1001182?",
            "Show available stock in warehouse PBAR",
            "List open warehouse orders in PBAR",
            "Show inbound deliveries for plant BAR1",
            "Stock transfer from 3PL to FEN1 via IM: 1 KG of material 1313284",
            "Transfer material 1313284 from 3PL PRO6 to FEN1, 1 KG",
        ],
    )
    agent_card = AgentCard(
        name="warehouse-agent",
        description=(
            "AI Agent for SAP S/4HANA Warehousing and Production — "
            "EWM Stock, Warehouse Orders, Inbound/Outbound Deliveries, "
            "Production Order Tracking, Component Availability, and Goods Movements"
        ),
        url=os.environ.get("AGENT_PUBLIC_URL", f"http://{host}:{port}/"),
        version="1.0.0",
        default_input_modes=["text", "text/plain"],
        default_output_modes=["text", "text/plain"],
        capabilities=AgentCapabilities(streaming=True, push_notifications=False),
        skills=[skill],
    )
    server = A2AStarletteApplication(
        agent_card=agent_card,
        http_handler=DefaultRequestHandler(
            agent_executor=AgentExecutor(),
            task_store=InMemoryTaskStore(),
        ),
    )
    app = server.build()
    app.add_middleware(JWTContextMiddleware)
    if _STARLETTE_INSTRUMENTED and StarletteInstrumentor is not None:
        StarletteInstrumentor().instrument_app(app)
    logger.info("Starting Warehouse A2A server at http://%s:%s", host, port)
    uvicorn.run(app, host=host, port=port)


def _build_asgi_app():
    skill = AgentSkill(
        id="warehouse-agent",
        name="warehouse-agent",
        description="AI Agent for SAP S/4HANA Warehousing and Production",
        tags=["warehouse", "stock", "delivery", "goods-receipt", "production", "ewm", "pp", "sto", "transfer"],
        examples=[
            "List released production orders for plant BAR1",
            "Show details for production order 1001176",
            "Show components for production order 1001176",
            "Show operations for production order 1001176",
            "Show available stock in warehouse PBAR",
            "List open warehouse orders in PBAR",
            "Stock transfer from 3PL to FEN1 via IM: 1 KG of material 1313284",
            "Transfer material 1313284 from 3PL PRO6 to FEN1, 1 KG",
        ],
    )
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8080"))
    card = AgentCard(
        name="warehouse-agent",
        description="AI Agent for SAP S/4HANA Warehousing",
        url=os.environ.get("AGENT_PUBLIC_URL", f"http://{host}:{port}/"),
        version="1.0.0",
        default_input_modes=["text", "text/plain"],
        default_output_modes=["text", "text/plain"],
        capabilities=AgentCapabilities(streaming=True, push_notifications=False),
        skills=[skill],
    )
    srv = A2AStarletteApplication(
        agent_card=card,
        http_handler=DefaultRequestHandler(
            agent_executor=AgentExecutor(),
            task_store=InMemoryTaskStore(),
        ),
    )
    asgi = srv.build()
    asgi.add_middleware(JWTContextMiddleware)
    if _STARLETTE_INSTRUMENTED and StarletteInstrumentor is not None:
        StarletteInstrumentor().instrument_app(asgi)
    return asgi


application = _build_asgi_app()

if __name__ == "__main__":
    main()
