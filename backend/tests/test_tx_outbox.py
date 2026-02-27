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
from src.models.tx_outbox import TxOutbox

ORACLE_SECRET = "test-oracle-secret"


def _sign(secret: str, payload: str) -> str:
    return hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()


def _oracle_headers(
    path: str, body: bytes, request_id: str, *, idem: str, method: str = "POST"
) -> dict[str, str]:
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


def test_tx_outbox_enqueue_claim_complete_happy_path(_client: TestClient) -> None:
    enqueue_path = "/api/v1/oracle/tx-outbox"
    enqueue_body = json.dumps(
        {"task_type": "noop", "payload": {"x": 1}, "idempotency_key": "idem-1"},
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

    claim_path = f"/api/v1/oracle/tx-outbox/{task_id}/claim"
    claim_body = json.dumps({"worker_id": "w1"}, separators=(",", ":"), sort_keys=True).encode("utf-8")
    resp = _client.post(
        claim_path,
        content=claim_body,
        headers=_oracle_headers(claim_path, claim_body, "req-claim", idem="idem-claim"),
    )
    assert resp.status_code == 200
    assert resp.json()["success"] is True
    assert resp.json()["data"]["task"]["status"] == "processing"

    complete_path = f"/api/v1/oracle/tx-outbox/{task_id}/complete"
    complete_body = json.dumps({"status": "succeeded", "error_hint": None}, separators=(",", ":"), sort_keys=True).encode("utf-8")
    resp = _client.post(
        complete_path,
        content=complete_body,
        headers=_oracle_headers(complete_path, complete_body, "req-comp", idem="idem-comp"),
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "succeeded"


def test_tx_outbox_claim_next_claims_oldest_pending(_client: TestClient) -> None:
    enqueue_path = "/api/v1/oracle/tx-outbox"
    for i in range(2):
        body = json.dumps(
            {"task_type": "noop", "payload": {"i": i}, "idempotency_key": f"idem-{i}"},
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        resp = _client.post(
            enqueue_path,
            content=body,
            headers=_oracle_headers(enqueue_path, body, f"req-enq-{i}", idem=f"idem-enq-{i}"),
        )
        assert resp.status_code == 200

    claim_next_path = "/api/v1/oracle/tx-outbox/claim-next"
    claim_body = json.dumps({"worker_id": "w-next"}, separators=(",", ":"), sort_keys=True).encode("utf-8")
    resp = _client.post(
        claim_next_path,
        content=claim_body,
        headers=_oracle_headers(claim_next_path, claim_body, "req-claim-next", idem="idem-claim-next"),
    )
    assert resp.status_code == 200
    assert resp.json()["success"] is True
    task = resp.json()["data"]["task"]
    assert task["status"] == "processing"
    assert task["locked_by"] == "w-next"
    assert task["payload"]["i"] == 0


def test_tx_outbox_pending_requires_hmac_and_lists_items(_client: TestClient) -> None:
    enqueue_path = "/api/v1/oracle/tx-outbox"
    body = json.dumps(
        {"task_type": "noop", "payload": {"x": 1}, "idempotency_key": "idem-pending-1"},
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    resp = _client.post(
        enqueue_path,
        content=body,
        headers=_oracle_headers(enqueue_path, body, "req-enq-p", idem="idem-enq-p"),
    )
    assert resp.status_code == 200

    pending_path = "/api/v1/oracle/tx-outbox/pending?limit=10"
    pending_sign_path = "/api/v1/oracle/tx-outbox/pending"
    # Signed GET with empty body.
    resp = _client.get(
        pending_path,
        headers=_oracle_headers(pending_sign_path, b"", "req-pending", idem="idem-pending", method="GET"),
    )
    assert resp.status_code == 200
    assert resp.json()["success"] is True
    assert len(resp.json()["data"]["items"]) >= 1


def test_tx_outbox_update_persists_tx_hash_and_result(_client: TestClient, _db: sessionmaker[Session]) -> None:
    enqueue_path = "/api/v1/oracle/tx-outbox"
    enqueue_body = json.dumps(
        {"task_type": "noop", "payload": {"x": 1}, "idempotency_key": "idem-upd-1"},
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    resp = _client.post(
        enqueue_path,
        content=enqueue_body,
        headers=_oracle_headers(enqueue_path, enqueue_body, "req-enq-upd", idem="idem-enq-upd"),
    )
    assert resp.status_code == 200
    task_id = resp.json()["data"]["task_id"]

    # Claim so task is in processing (update is allowed for pending too, but this matches worker behavior).
    claim_path = f"/api/v1/oracle/tx-outbox/{task_id}/claim"
    claim_body = json.dumps({"worker_id": "w-upd"}, separators=(",", ":"), sort_keys=True).encode("utf-8")
    resp = _client.post(
        claim_path,
        content=claim_body,
        headers=_oracle_headers(claim_path, claim_body, "req-claim-upd", idem="idem-claim-upd"),
    )
    assert resp.status_code == 200

    update_path = f"/api/v1/oracle/tx-outbox/{task_id}/update"
    update_body = json.dumps(
        {"tx_hash": "0x" + "c" * 64, "result": {"stage": "submitted"}},
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    resp = _client.post(
        update_path,
        content=update_body,
        headers=_oracle_headers(update_path, update_body, "req-upd", idem="idem-upd"),
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["tx_hash"] == "0x" + "c" * 64
    assert resp.json()["data"]["result"]["stage"] == "submitted"

    with _db() as db:
        row = db.query(TxOutbox).filter(TxOutbox.task_id == task_id).first()
        assert row is not None
        assert row.tx_hash == "0x" + "c" * 64
        assert row.result_json is not None


def test_tx_outbox_claim_next_reclaims_stale_processing_task(_client: TestClient, _db: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch) -> None:
    # Make lock TTL tiny so we can deterministically reclaim.
    monkeypatch.setenv("TX_OUTBOX_LOCK_TTL_SECONDS", "1")

    enqueue_path = "/api/v1/oracle/tx-outbox"
    enqueue_body = json.dumps(
        {"task_type": "noop", "payload": {"x": 1}, "idempotency_key": "idem-stale-1"},
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

    # Manually mark task as stale processing in DB.
    with _db() as db:
        row = db.query(TxOutbox).filter(TxOutbox.task_id == task_id).first()
        assert row is not None
        row.status = "processing"
        row.locked_at = datetime.now(timezone.utc) - timedelta(seconds=10)
        row.locked_by = "w-old"
        db.commit()

    claim_next_path = "/api/v1/oracle/tx-outbox/claim-next"
    claim_body = json.dumps({"worker_id": "w-new"}, separators=(",", ":"), sort_keys=True).encode("utf-8")
    resp = _client.post(
        claim_next_path,
        content=claim_body,
        headers=_oracle_headers(claim_next_path, claim_body, "req-claim-stale", idem="idem-claim-stale"),
    )
    assert resp.status_code == 200
    assert resp.json()["success"] is True
    assert resp.json()["data"]["task"]["task_id"] == task_id
    assert resp.json()["data"]["task"]["locked_by"] == "w-new"


def test_tx_outbox_complete_pending_requeues_and_clears_tx_state(_client: TestClient, _db: sessionmaker[Session]) -> None:
    enqueue_path = "/api/v1/oracle/tx-outbox"
    enqueue_body = json.dumps(
        {"task_type": "noop", "payload": {"x": 1}, "idempotency_key": "idem-requeue-1"},
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    resp = _client.post(
        enqueue_path,
        content=enqueue_body,
        headers=_oracle_headers(enqueue_path, enqueue_body, "req-enq-requeue", idem="idem-enq-requeue"),
    )
    assert resp.status_code == 200
    task_id = resp.json()["data"]["task_id"]

    claim_path = f"/api/v1/oracle/tx-outbox/{task_id}/claim"
    claim_body = json.dumps({"worker_id": "w-requeue"}, separators=(",", ":"), sort_keys=True).encode("utf-8")
    resp = _client.post(
        claim_path,
        content=claim_body,
        headers=_oracle_headers(claim_path, claim_body, "req-claim-requeue", idem="idem-claim-requeue"),
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["task"]["status"] == "processing"

    complete_path = f"/api/v1/oracle/tx-outbox/{task_id}/complete"
    complete_body = json.dumps(
        {
            "status": "pending",
            "error_hint": "rpc_error",
            "tx_hash": "0x" + "a" * 64,
            "result": {"stage": "retry_pending"},
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    resp = _client.post(
        complete_path,
        content=complete_body,
        headers=_oracle_headers(complete_path, complete_body, "req-comp-requeue", idem="idem-comp-requeue"),
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "pending"
    assert resp.json()["data"]["tx_hash"] is None
    assert resp.json()["data"]["locked_by"] is None
    assert resp.json()["data"]["last_error_hint"] == "rpc_error"

    with _db() as db:
        row = db.query(TxOutbox).filter(TxOutbox.task_id == task_id).first()
        assert row is not None
        assert row.status == "pending"
        assert row.tx_hash is None
        assert row.locked_at is None
        assert row.locked_by is None


def test_tx_outbox_complete_blocked_finalizes_task(_client: TestClient, _db: sessionmaker[Session]) -> None:
    enqueue_path = "/api/v1/oracle/tx-outbox"
    enqueue_body = json.dumps(
        {"task_type": "create_distribution", "payload": {"x": 1}, "idempotency_key": "idem-blocked-1"},
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    resp = _client.post(
        enqueue_path,
        content=enqueue_body,
        headers=_oracle_headers(enqueue_path, enqueue_body, "req-enq-blocked", idem="idem-enq-blocked"),
    )
    assert resp.status_code == 200
    task_id = resp.json()["data"]["task_id"]

    claim_path = f"/api/v1/oracle/tx-outbox/{task_id}/claim"
    claim_body = json.dumps({"worker_id": "w-blocked"}, separators=(",", ":"), sort_keys=True).encode("utf-8")
    resp = _client.post(
        claim_path,
        content=claim_body,
        headers=_oracle_headers(claim_path, claim_body, "req-claim-blocked", idem="idem-claim-blocked"),
    )
    assert resp.status_code == 200

    complete_path = f"/api/v1/oracle/tx-outbox/{task_id}/complete"
    complete_body = json.dumps(
        {
            "status": "blocked",
            "error_hint": "safe_execution_required",
            "result": {"stage": "safe_execution_required"},
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    resp = _client.post(
        complete_path,
        content=complete_body,
        headers=_oracle_headers(complete_path, complete_body, "req-comp-blocked", idem="idem-comp-blocked"),
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "blocked"
    assert resp.json()["data"]["last_error_hint"] == "safe_execution_required"

    with _db() as db:
        row = db.query(TxOutbox).filter(TxOutbox.task_id == task_id).first()
        assert row is not None
        assert row.status == "blocked"
