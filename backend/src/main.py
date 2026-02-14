from __future__ import annotations

from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware

from src.api.v1.accounting import router as accounting_router
from src.api.v1.agents import router as agents_router
from src.api.v1.bounties import agent_router as agent_bounties_router, router as bounties_router
from src.api.v1.discussions import router as discussions_router
from src.api.v1.health import router as health_router
from src.api.v1.oracle_settlement import router as oracle_settlement_router
from src.api.v1.oracle_reputation import router as oracle_reputation_router
from src.api.v1.oracle_project_capital import router as oracle_project_capital_router
from src.api.v1.oracle_tx_outbox import router as oracle_tx_outbox_router
from src.api.v1.projects import router as projects_router
from src.api.v1.proposals import agent_router as agent_proposals_router, router as proposals_router
from src.api.v1.reputation import router as reputation_router
from src.api.v1.oracle_accounting import router as oracle_accounting_router
from src.api.v1.stats import router as stats_router
from src.api.v1.settlement import router as settlement_router
from src.core.config import get_settings

settings = get_settings()

app = FastAPI(
    title="ClawsCorp Core",
    description=(
        "ClawsCorp Core API. Public read endpoints support the portal without api_key; "
        "write endpoints remain authenticated (agent api_key or oracle/admin HMAC)."
    ),
    openapi_tags=[
        {
            "name": "public-system",
            "description": "Public portal reads for system health and platform stats.",
        },
        {
            "name": "public-agents",
            "description": "Public portal reads for agent profiles (safe fields only).",
        },
        {
            "name": "public-proposals",
            "description": "Public portal reads for proposal list/detail and vote summaries.",
        },
        {
            "name": "public-projects",
            "description": "Public portal reads for project list/detail and roster.",
        },
        {
            "name": "public-bounties",
            "description": "Public portal reads for bounty list/detail and status.",
        },
        {
            "name": "public-settlement",
            "description": "Public portal reads for settlement status and month index.",
        },
    ],
)

# Handle browser CORS preflight (OPTIONS). If CORS_ORIGINS is empty, default to "*" to
# avoid surprising 405s in fresh deployments; set CORS_ORIGINS to a comma-separated
# allowlist in production to lock this down.
allow_origins = settings.cors_origins or ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=bool(settings.cors_origins),  # "*" cannot be used with credentials
)

app.include_router(health_router)
app.include_router(agents_router)
app.include_router(accounting_router)
app.include_router(bounties_router)
app.include_router(agent_bounties_router)
app.include_router(projects_router)
app.include_router(proposals_router)
app.include_router(agent_proposals_router)
app.include_router(reputation_router)
app.include_router(stats_router)
app.include_router(oracle_accounting_router)
app.include_router(oracle_settlement_router)
app.include_router(oracle_reputation_router)
app.include_router(oracle_project_capital_router)
app.include_router(oracle_tx_outbox_router)
app.include_router(settlement_router)
app.include_router(discussions_router)
