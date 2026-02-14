from __future__ import annotations

import hashlib
import hmac
import json
import sys
import time
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

# Make `src` importable whether pytest runs from repo root or backend/.
BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from src.api.v1.oracle_settlement import router as oracle_router
from src.core.config import get_settings
from src.core.database import Base, get_db
from src.core.security import build_oracle_hmac_v2_payload

import src.models  # noqa: F401
from src.models.agent import Agent
from src.models.project import Project, ProjectStatus
from src.models.reconciliation_report import ReconciliationReport
from src.models.revenue_event import RevenueEvent
from src.models.expense_event import ExpenseEvent
from src.models.settlement import Settlement


ORACLE_SECRET = "test-oracle-secret"


def _sign(secret: str, payload: str) -> str:
    return hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()


def _make_test_app(db_session_factory: sessionmaker[Session]) -> FastAPI:
    app = FastAPI()

    def _override_get_db():
        db = db_session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_get_db
    app.include_router(oracle_router)
    return app


@pytest.fixture(autouse=True)
def _isolate_settings_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ORACLE_HMAC_SECRET", ORACLE_SECRET)
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
def _client(_db: sessionmaker[Session]) -> TestClient:
    app = _make_test_app(_db)
    return TestClient(app, raise_server_exceptions=False)


def _post_signed(client: TestClient, *, request_id: str, path: str, body: bytes) -> tuple[int, dict]:
    body_hash = hashlib.sha256(body).hexdigest()
    timestamp = str(int(time.time()))
    payload = build_oracle_hmac_v2_payload(timestamp, request_id, "POST", path, body_hash)
    signature = _sign(ORACLE_SECRET, payload)
    resp = client.post(
        path,
        content=body,
        headers={
            "X-Request-Timestamp": timestamp,
            "X-Request-Id": request_id,
            "X-Signature": signature,
            "Content-Type": "application/json",
        },
    )
    return resp.status_code, resp.json()


def test_execute_payload_includes_originator_wallet_weighted_by_project_profit(
    _client: TestClient,
    _db: sessionmaker[Session],
) -> None:
    month = "202501"
    with _db() as db:
        agent = Agent(
            agent_id="ag_origin",
            name="Origin",
            capabilities_json="[]",
            wallet_address="0x1111111111111111111111111111111111111111",
            api_key_hash="x",
            api_key_last4="xxxx",
        )
        db.add(agent)
        db.flush()

        project = Project(
            project_id="proj_1",
            slug="proj-1",
            name="Project 1",
            description_md=None,
            status=ProjectStatus.active,
            proposal_id=None,
            origin_proposal_id=None,
            originator_agent_id=agent.id,
            discussion_thread_id=None,
            treasury_wallet_address=None,
            treasury_address=None,
            revenue_wallet_address=None,
            revenue_address=None,
            monthly_budget_micro_usdc=None,
            created_by_agent_id=agent.id,
        )
        db.add(project)
        db.flush()

        # Profit=1000-200=800
        db.add(
            RevenueEvent(
                event_id="rev_1",
                profit_month_id=month,
                project_id=project.id,
                amount_micro_usdc=1000,
                tx_hash=None,
                source="billing",
                idempotency_key="rev:1",
                evidence_url=None,
            )
        )
        db.add(
            ExpenseEvent(
                event_id="exp_1",
                profit_month_id=month,
                project_id=project.id,
                amount_micro_usdc=200,
                tx_hash=None,
                category="ops",
                idempotency_key="exp:1",
                evidence_url=None,
            )
        )

        db.add(
            Settlement(
                profit_month_id=month,
                revenue_sum_micro_usdc=1000,
                expense_sum_micro_usdc=200,
                profit_sum_micro_usdc=800,
                profit_nonnegative=True,
            )
        )
        db.add(
            ReconciliationReport(
                profit_month_id=month,
                revenue_sum_micro_usdc=1000,
                expense_sum_micro_usdc=200,
                profit_sum_micro_usdc=800,
                distributor_balance_micro_usdc=800,
                delta_micro_usdc=0,
                ready=True,
                blocked_reason=None,
                rpc_chain_id=None,
                rpc_url_name=None,
            )
        )
        db.commit()

    path = f"/api/v1/oracle/distributions/{month}/execute/payload"
    status, payload = _post_signed(_client, request_id="req_1", path=path, body=b"{}")
    assert status == 200, payload
    assert payload["success"] is True
    data = payload["data"]
    assert data["status"] == "ok"
    assert data["blocked_reason"] is None
    assert data["stakers"] == []
    assert data["authors"] == ["0x1111111111111111111111111111111111111111"]
    assert data["author_shares"] == [800]


def test_execute_payload_caps_authors_to_50(_client: TestClient, _db: sessionmaker[Session]) -> None:
    month = "202501"
    with _db() as db:
        # Settlement+reconciliation ok.
        db.add(
            Settlement(
                profit_month_id=month,
                revenue_sum_micro_usdc=100,
                expense_sum_micro_usdc=0,
                profit_sum_micro_usdc=100,
                profit_nonnegative=True,
            )
        )
        db.add(
            ReconciliationReport(
                profit_month_id=month,
                revenue_sum_micro_usdc=100,
                expense_sum_micro_usdc=0,
                profit_sum_micro_usdc=100,
                distributor_balance_micro_usdc=100,
                delta_micro_usdc=0,
                ready=True,
                blocked_reason=None,
                rpc_chain_id=None,
                rpc_url_name=None,
            )
        )
        db.commit()

        for i in range(60):
            addr = f"0x{(i+1):040x}"
            agent = Agent(
                agent_id=f"ag_{i}",
                name=f"A{i}",
                capabilities_json="[]",
                wallet_address=addr,
                api_key_hash="x",
                api_key_last4="xxxx",
            )
            db.add(agent)
            db.flush()
            project = Project(
                project_id=f"proj_{i}",
                slug=f"proj-{i}",
                name=f"Project {i}",
                description_md=None,
                status=ProjectStatus.active,
                proposal_id=None,
                origin_proposal_id=None,
                originator_agent_id=agent.id,
                discussion_thread_id=None,
                treasury_wallet_address=None,
                treasury_address=None,
                revenue_wallet_address=None,
                revenue_address=None,
                monthly_budget_micro_usdc=None,
                created_by_agent_id=agent.id,
            )
            db.add(project)
            db.flush()
            db.add(
                RevenueEvent(
                    event_id=f"rev_{i}",
                    profit_month_id=month,
                    project_id=project.id,
                    amount_micro_usdc=1,
                    tx_hash=None,
                    source="billing",
                    idempotency_key=f"rev:{i}",
                    evidence_url=None,
                )
            )
        db.commit()

    path = f"/api/v1/oracle/distributions/{month}/execute/payload"
    status, payload = _post_signed(_client, request_id="req_2", path=path, body=b"{}")
    assert status == 200, payload
    assert payload["success"] is True
    data = payload["data"]
    assert data["status"] == "ok"
    assert len(data["authors"]) == 50
    assert f"authors_capped_to_50" in (data.get("notes") or [])

