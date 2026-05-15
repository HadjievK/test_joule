# CRITICAL: Initialize telemetry BEFORE importing AI frameworks
from sap_cloud_sdk.aicore import set_aicore_config
from sap_cloud_sdk.core.telemetry import auto_instrument

set_aicore_config()
auto_instrument()

import logging
import os

import click
import uvicorn
from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import AgentCapabilities, AgentCard, AgentSkill

from agent_executor import AgentExecutor
from hana_cache import cache_stats
from opentelemetry.instrumentation.starlette import StarletteInstrumentor

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "5000"))


@click.command()
@click.option("--host", default=HOST)
@click.option("--port", default=PORT)
def main(host: str, port: int):
    skill = AgentSkill(
        id="payroll-operations-agent",
        name="payroll-operations-agent",
        description="AI agent that controls all payroll operations across SAP SuccessFactors Employee Central Payroll and SAP HANA Cloud â including payroll data retrieval, run initiation, discrepancy detection and resolution, compliance validation, and report generation.",
        tags=["payroll", "operations", "agent"],
        examples=[
            "Show me the payroll run status for the current period across both systems",
            "Validate time sheets for all employees and flag any missing entries",
        ],
    )
    agent_card = AgentCard(
        name="payroll-operations-agent",
        description="AI agent that controls all payroll operations across SAP SuccessFactors Employee Central Payroll and SAP HANA Cloud â including payroll data retrieval, run initiation, discrepancy detection and resolution, compliance validation, and report generation.",
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

    # Expose HANA cache stats at /cache/stats for operational monitoring
    from starlette.requests import Request
    from starlette.responses import JSONResponse
    from starlette.routing import Route

    async def hana_cache_stats_endpoint(request: Request) -> JSONResponse:
        return JSONResponse(cache_stats())

    from starlette.routing import Router
    app.routes.append(Route("/cache/stats", hana_cache_stats_endpoint, methods=["GET"]))

    StarletteInstrumentor().instrument_app(app)

    logger.info(f"Starting A2A server at http://{host}:{port}")
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
