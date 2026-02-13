from __future__ import annotations

import hashlib
import hmac
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from src.core.config import get_settings
from src.core.database import Base, get_db
from src.core.security import build_oracle_hmac_v2_payload
from src.main import app

import src.models  # noqa: F401
from src.models.audit_log import AuditLog
from src.models.project import Project, ProjectStatus
from src.models.project_capital_event import ProjectCapitalEvent
from src.models.project_capital_reconciliation_report import ProjectCapitalReconciliationReport

ORACLE_SECRET = "test-oracle-secret"


def _sign(secret: str, payload: str) -> str:
    return hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()


def _oracle_headers(path: str, body: bytes, request_id: str, *, idem: str) -> dict[str, str]:
    timestamp = str(int(time.time()))
    body_hash = hashlib.sha256(body).hexdigest()
    payload = build_oracle_hmac_v2_payload(timestamp, request_id, "POST", path, body_hash)
    return {
        "Content-Type": "application/json",
        "X-Request-Timestamp": timestamp,
        "X-Request-Id": request_id,
        "Idempotency-Key": idem,
        "X-Signature": _sign(ORACLE_SECRET, payload),
    }


@pytest.fixture(autouse=True)
def _isolate_settings_cache() -> None:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture()
def _db() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)
    return session_local


@pytest.fixture()
def _client(_db: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("ORACLE_HMAC_SECRET", ORACLE_SECRET)
    monkeypatch.setenv("ORACLE_REQUEST_TTL_SECONDS", "300")
    monkeypatch.setenv("ORACLE_CLOCK_SKEW_SECONDS", "5")
    monkeypatch.setenv("ORACLE_ACCEPT_LEGACY_SIGNATURES", "false")
    monkeypatch.setenv("PROJECT_CAPITAL_RECONCILIATION_MAX_AGE_SECONDS", "3600")

    def _override_get_db():
        db = _db()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_get_db
    client = TestClient(app, raise_server_exceptions=False)
    try:
        yield client
    finally:
        app.dependency_overrides.clear()


def _seed_project(db: Session) -> Project:
    project = Project(
        project_id="prj_cap_gate_1",
        slug="cap-gate-prj",
        name="Capital Gate Project",
        status=ProjectStatus.active,
        treasury_address="0x" + "1" * 40,
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


def _insert_reconciliation(
    db: Session,
    *,
    project_id: int,
    ready: bool,
    delta_micro_usdc: int | None,
    computed_at: datetime,
) -> None:
    db.add(
        ProjectCapitalReconciliationReport(
            project_id=project_id,
            treasury_address="0x" + "1" * 40,
            ledger_balance_micro_usdc=10_000_000,
            onchain_balance_micro_usdc=10_000_000,
            delta_micro_usdc=delta_micro_usdc,
            ready=ready,
            blocked_reason=None if ready and delta_micro_usdc == 0 else "balance_mismatch",
            computed_at=computed_at,
        )
    )
    db.commit()


def _call_outflow(client: TestClient, *, idem: str) -> tuple[int, dict[str, object]]:
    path = "/api/v1/oracle/project-capital-events"
    body = json.dumps(
        {
            "idempotency_key": idem,
            "profit_month_id": "202602",
            "project_id": "prj_cap_gate_1",
            "delta_micro_usdc": -1_000_000,
            "source": "manual_outflow",
            "evidence_tx_hash": "0x" + "a" * 64,
            "evidence_url": "test",
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    resp = client.post(path, content=body, headers=_oracle_headers(path, body, f"req-{idem}", idem=idem))
    return resp.status_code, resp.json()


def _latest_audit(db: Session) -> AuditLog | None:
    return (
        db.query(AuditLog)
        .filter(AuditLog.path == "/api/v1/oracle/project-capital-events")
        .order_by(AuditLog.id.desc())
        .first()
    )


def test_outflow_blocked_when_reconciliation_missing(_client: TestClient, _db: sessionmaker[Session]) -> None:
    with _db() as db:
        _seed_project(db)

    status_code, data = _call_outflow(_client, idem="idem-outflow-missing")
    assert status_code == 200
    assert data["success"] is False
    assert data["blocked_reason"] == "project_capital_reconciliation_missing"
    assert data["data"] is None

    with _db() as db:
        assert db.query(ProjectCapitalEvent).count() == 0
        audit = _latest_audit(db)
        assert audit is not None
        assert audit.idempotency_key == "idem-outflow-missing"
        assert audit.error_hint is not None
        assert "br=project_capital_reconciliation_missing;" in audit.error_hint


def test_outflow_blocked_when_reconciliation_not_ready(_client: TestClient, _db: sessionmaker[Session]) -> None:
    with _db() as db:
        project = _seed_project(db)
        _insert_reconciliation(
            db,
            project_id=project.id,
            ready=False,
            delta_micro_usdc=50,
            computed_at=datetime.now(timezone.utc),
        )

    status_code, data = _call_outflow(_client, idem="idem-outflow-not-ready")
    assert status_code == 200
    assert data["success"] is False
    assert data["blocked_reason"] == "project_capital_not_reconciled"

    with _db() as db:
        assert db.query(ProjectCapitalEvent).count() == 0


def test_outflow_blocked_when_reconciliation_stale(_client: TestClient, _db: sessionmaker[Session]) -> None:
    with _db() as db:
        project = _seed_project(db)
        _insert_reconciliation(
            db,
            project_id=project.id,
            ready=True,
            delta_micro_usdc=0,
            computed_at=datetime.now(timezone.utc) - timedelta(hours=2),
        )

    status_code, data = _call_outflow(_client, idem="idem-outflow-stale")
    assert status_code == 200
    assert data["success"] is False
    assert data["blocked_reason"] == "project_capital_reconciliation_stale"

    with _db() as db:
        assert db.query(ProjectCapitalEvent).count() == 0


def test_outflow_allows_fresh_ready_reconciliation(_client: TestClient, _db: sessionmaker[Session]) -> None:
    with _db() as db:
        project = _seed_project(db)
        _insert_reconciliation(
            db,
            project_id=project.id,
            ready=True,
            delta_micro_usdc=0,
            computed_at=datetime.now(timezone.utc),
        )

    status_code, data = _call_outflow(_client, idem="idem-outflow-ok")
    assert status_code == 200
    assert data["success"] is True
    assert data["blocked_reason"] is None
    assert data["data"]["delta_micro_usdc"] == -1_000_000

    with _db() as db:
        assert db.query(ProjectCapitalEvent).count() == 1

