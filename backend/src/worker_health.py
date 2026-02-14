# SPDX-License-Identifier: BSL-1.1

from __future__ import annotations

import os

from fastapi import FastAPI

app = FastAPI(title="worker-health")


@app.get("/api/v1/health")
def health() -> dict[str, object]:
    # Keep this endpoint dependency-free so worker services can pass Railway healthchecks
    # even when DB/RPC is temporarily unavailable.
    return {"status": "ok", "service": os.getenv("SERVICE_NAME", "worker")}

