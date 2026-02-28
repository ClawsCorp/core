from __future__ import annotations

import sys
from pathlib import Path

from fastapi.testclient import TestClient

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from src.main import app


def test_generated_project_artifact_summary_route_returns_read_api_payload() -> None:
    client = TestClient(app, raise_server_exceptions=False)
    try:
        response = client.get("/api/v1/project-artifacts/autonomy-pilot-concierge-saas-454af1/summary")
        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        data = body["data"]
        assert data["slug"] == "autonomy-pilot-concierge-saas-454af1"
        assert data["route_kind"] == "summary_template"
        assert data["status"] == "ready"
        assert data["links"]["portal_app_path"] == "/apps/autonomy-pilot-concierge-saas-454af1"
    finally:
        client.close()
