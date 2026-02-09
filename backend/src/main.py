from __future__ import annotations

from fastapi import FastAPI

from api.v1.agents import router as agents_router
from api.v1.health import router as health_router

app = FastAPI(title="ClawsCorp Core")
app.include_router(health_router)
app.include_router(agents_router)
