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
from src.models.git_outbox import GitOutbox

ORACLE_SECRET = "test-oracle-secret"


def _sign(secret: str, payload: str) -> str:
    return hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()


def _oracle_headers(path: str, body: bytes, request_id: str, *, idem: str, method: str = "POST") -> dict[str, str]:
    timestamp = str(int(time.time()))
    body_hash = hashlib.sha256(body).hexdigest()
    payload = build_oracle_hmac_v2_payload(timestamp, request_id, method, path, body_hash)
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


def test_git_outbox_enqueue_claim_update_complete_happy_path(_client: TestClient, _db: sessionmaker[Session]) -> None:
    enqueue_path = "/api/v1/oracle/git-outbox"
    enqueue_body = json.dumps(
        {
            "task_type": "create_app_surface_commit",
            "payload": {"slug": "aurora-notes"},
            "idempotency_key": "git-idem-1",
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    resp = _client.post(
        enqueue_path,
        content=enqueue_body,
        headers=_oracle_headers(enqueue_path, enqueue_body, "req-enq", idem="idem-enq"),
    )
    assert resp.status_code == 200
    task_id = resp.json()["data"]["task_id"]
    assert resp.json()["data"]["status"] == "pending"

    claim_next_path = "/api/v1/oracle/git-outbox/claim-next"
    claim_body = json.dumps({"worker_id": "git-worker-1"}, separators=(",", ":"), sort_keys=True).encode("utf-8")
    resp_claim = _client.post(
        claim_next_path,
        content=claim_body,
        headers=_oracle_headers(claim_next_path, claim_body, "req-claim", idem="idem-claim"),
    )
    assert resp_claim.status_code == 200
    assert resp_claim.json()["success"] is True
    assert resp_claim.json()["data"]["task"]["task_id"] == task_id
    assert resp_claim.json()["data"]["task"]["status"] == "processing"

    update_path = f"/api/v1/oracle/git-outbox/{task_id}/update"
    update_body = json.dumps(
        {
            "result": {"stage": "committed"},
            "branch_name": "codex/dao-surface-aurora-notes-ab12cd",
            "commit_sha": "a" * 40,
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    resp_update = _client.post(
        update_path,
        content=update_body,
        headers=_oracle_headers(update_path, update_body, "req-upd", idem="idem-upd"),
    )
    assert resp_update.status_code == 200
    assert resp_update.json()["data"]["branch_name"].startswith("codex/")
    assert resp_update.json()["data"]["commit_sha"] == "a" * 40

    complete_path = f"/api/v1/oracle/git-outbox/{task_id}/complete"
    complete_body = json.dumps(
        {
            "status": "succeeded",
            "result": {"stage": "done"},
            "branch_name": "codex/dao-surface-aurora-notes-ab12cd",
            "commit_sha": "b" * 40,
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    resp_complete = _client.post(
        complete_path,
        content=complete_body,
        headers=_oracle_headers(complete_path, complete_body, "req-comp", idem="idem-comp"),
    )
    assert resp_complete.status_code == 200
    assert resp_complete.json()["data"]["status"] == "succeeded"
    assert resp_complete.json()["data"]["commit_sha"] == "b" * 40

    with _db() as db:
        row = db.query(GitOutbox).filter(GitOutbox.task_id == task_id).first()
        assert row is not None
        assert row.status == "succeeded"
        assert row.commit_sha == "b" * 40


def test_git_outbox_claim_next_reclaims_stale_processing_task(
    _client: TestClient,
    _db: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TX_OUTBOX_LOCK_TTL_SECONDS", "1")

    enqueue_path = "/api/v1/oracle/git-outbox"
    enqueue_body = json.dumps(
        {
            "task_type": "noop",
            "payload": {},
            "idempotency_key": "git-idem-stale-1",
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    resp = _client.post(
        enqueue_path,
        content=enqueue_body,
        headers=_oracle_headers(enqueue_path, enqueue_body, "req-enq-stale", idem="idem-enq-stale"),
    )
    assert resp.status_code == 200
    task_id = resp.json()["data"]["task_id"]

    with _db() as db:
        row = db.query(GitOutbox).filter(GitOutbox.task_id == task_id).first()
        assert row is not None
        row.status = "processing"
        row.locked_at = datetime.now(timezone.utc) - timedelta(seconds=10)
        row.locked_by = "old-worker"
        db.commit()

    claim_next_path = "/api/v1/oracle/git-outbox/claim-next"
    claim_body = json.dumps({"worker_id": "new-worker"}, separators=(",", ":"), sort_keys=True).encode("utf-8")
    resp_claim = _client.post(
        claim_next_path,
        content=claim_body,
        headers=_oracle_headers(claim_next_path, claim_body, "req-claim-stale", idem="idem-claim-stale"),
    )
    assert resp_claim.status_code == 200
    assert resp_claim.json()["success"] is True
    assert resp_claim.json()["data"]["task"]["task_id"] == task_id
    assert resp_claim.json()["data"]["task"]["locked_by"] == "new-worker"
