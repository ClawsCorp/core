from __future__ import annotations

import time

from fastapi import Depends, HTTPException, Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.core.audit import record_audit
from src.core.config import get_settings
from src.core.database import get_db
from src.core.security import (
    build_oracle_hmac_v2_payload,
    hash_body,
    require_agent_api_key,
    verify_hmac_v1,
    verify_oracle_hmac_v2,
)
from src.models.agent import Agent
from src.models.oracle_nonce import OracleNonce


def require_agent_auth(
    *,
    agent: Agent = Depends(require_agent_api_key),
) -> Agent:
    return agent


async def require_oracle_hmac(
    request: Request,
    db: Session = Depends(get_db),
) -> str:
    settings = get_settings()
    timestamp = request.headers.get("X-Request-Timestamp")
    request_id = request.headers.get("X-Request-Id")
    signature = request.headers.get("X-Signature")
    idempotency_key = request.headers.get("Idempotency-Key")

    if not timestamp or not request_id or not signature:
        body_hash = hash_body(await request.body())
        request.state.body_hash = body_hash
        request.state.request_id = request_id
        request.state.signature_status = "invalid"
        _record_oracle_auth_audit(
            request,
            db,
            body_hash=body_hash,
            request_id=request_id,
            idempotency_key=idempotency_key,
            signature_status="invalid",
            error_hint="missing_required_oracle_headers",
        )
        raise HTTPException(status_code=403, detail="Invalid oracle authentication headers.")

    if not settings.oracle_hmac_secret:
        body_hash = hash_body(await request.body())
        request.state.body_hash = body_hash
        request.state.request_id = request_id
        request.state.signature_status = "invalid"
        _record_oracle_auth_audit(
            request,
            db,
            body_hash=body_hash,
            request_id=request_id,
            idempotency_key=idempotency_key,
            signature_status="invalid",
            error_hint="oracle_hmac_not_configured",
        )
        raise HTTPException(status_code=403, detail="Invalid signature.")

    if not _is_timestamp_fresh(timestamp, settings.oracle_request_ttl_seconds, settings.oracle_clock_skew_seconds):
        body_hash = hash_body(await request.body())
        request.state.body_hash = body_hash
        request.state.request_id = request_id
        request.state.signature_status = "stale"
        _record_oracle_auth_audit(
            request,
            db,
            body_hash=body_hash,
            request_id=request_id,
            idempotency_key=idempotency_key,
            signature_status="stale",
            error_hint="stale_or_invalid_timestamp",
        )
        raise HTTPException(status_code=403, detail="Stale oracle request timestamp.")

    existing_nonce = db.query(OracleNonce).filter(OracleNonce.request_id == request_id).first()
    if existing_nonce is not None:
        body_hash = hash_body(await request.body())
        request.state.body_hash = body_hash
        request.state.request_id = request_id
        request.state.signature_status = "replay"
        _record_oracle_auth_audit(
            request,
            db,
            body_hash=body_hash,
            request_id=request_id,
            idempotency_key=idempotency_key,
            signature_status="replay",
            error_hint="replayed_request_id",
        )
        raise HTTPException(status_code=409, detail="Replay detected.")

    body_bytes = await request.body()
    body_hash = hash_body(body_bytes)
    request.state.body_hash = body_hash
    request.state.request_id = request_id

    v2_payload = build_oracle_hmac_v2_payload(
        timestamp,
        request_id,
        request.method,
        request.url.path,
        body_hash,
    )
    is_valid_v2 = verify_oracle_hmac_v2(settings.oracle_hmac_secret, v2_payload, signature)

    signature_status = "ok" if is_valid_v2 else "invalid"
    if not is_valid_v2 and settings.oracle_accept_legacy_signatures:
        is_valid_legacy = verify_hmac_v1(settings.oracle_hmac_secret, timestamp, body_hash, signature)
        if is_valid_legacy:
            signature_status = "ok_legacy"

    if signature_status == "invalid":
        request.state.signature_status = "invalid"
        _record_oracle_auth_audit(
            request,
            db,
            body_hash=body_hash,
            request_id=request_id,
            idempotency_key=idempotency_key,
            signature_status="invalid",
            error_hint="invalid_oracle_signature",
        )
        raise HTTPException(status_code=403, detail="Invalid signature.")

    try:
        db.add(OracleNonce(request_id=request_id))
        db.commit()
    except IntegrityError:
        db.rollback()
        request.state.signature_status = "replay"
        _record_oracle_auth_audit(
            request,
            db,
            body_hash=body_hash,
            request_id=request_id,
            idempotency_key=idempotency_key,
            signature_status="replay",
            error_hint="replayed_request_id",
        )
        raise HTTPException(status_code=409, detail="Replay detected.")

    request.state.signature_status = signature_status
    return body_hash


def _is_timestamp_fresh(timestamp: str, ttl_seconds: int, clock_skew_seconds: int) -> bool:
    try:
        request_ts = int(timestamp)
    except (TypeError, ValueError):
        return False

    now_ts = int(time.time())
    if request_ts > now_ts + clock_skew_seconds:
        return False

    return now_ts - request_ts <= ttl_seconds + clock_skew_seconds


def _record_oracle_auth_audit(
    request: Request,
    db: Session,
    *,
    body_hash: str,
    request_id: str | None,
    idempotency_key: str | None,
    signature_status: str,
    error_hint: str,
) -> None:
    record_audit(
        db,
        actor_type="oracle",
        agent_id=None,
        method=request.method,
        path=request.url.path,
        idempotency_key=idempotency_key,
        body_hash=body_hash,
        signature_status=signature_status,
        request_id=request_id or "missing",
        error_hint=error_hint,
    )
