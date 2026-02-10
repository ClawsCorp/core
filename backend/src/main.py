from __future__ import annotations

from fastapi import FastAPI

from api.v1.accounting import router as accounting_router
from api.v1.agents import router as agents_router
from api.v1.bounties import router as bounties_router
from api.v1.health import router as health_router
from api.v1.oracle_settlement import router as oracle_settlement_router
from api.v1.projects import router as projects_router
from api.v1.proposals import router as proposals_router
from api.v1.reputation import router as reputation_router
from api.v1.oracle_accounting import router as oracle_accounting_router
from api.v1.stats import router as stats_router
from api.v1.settlement import router as settlement_router

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
app.include_router(health_router)
app.include_router(agents_router)
app.include_router(accounting_router)
app.include_router(bounties_router)
app.include_router(projects_router)
app.include_router(proposals_router)
app.include_router(reputation_router)
app.include_router(stats_router)
app.include_router(oracle_accounting_router)
app.include_router(oracle_settlement_router)
app.include_router(settlement_router)
