# SPDX-License-Identifier: BSL-1.1

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
from typing import Final
from uuid import uuid4

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from src.core.audit import record_audit
from src.core.database import get_db
from src.models.agent import Agent

logger = logging.getLogger(__name__)

PBKDF2_ALGORITHM: Final[str] = "sha256"
PBKDF2_ITERATIONS: Final[int] = 200_000
PBKDF2_SALT_BYTES: Final[int] = 16


def generate_api_key() -> str:
    return secrets.token_urlsafe(32)


def generate_agent_api_key(agent_id: str) -> str:
    return f"{agent_id}.{generate_api_key()}"


def api_key_last4(api_key: str) -> str:
    return api_key[-4:]


def hash_api_key(api_key: str) -> str:
    salt = secrets.token_bytes(PBKDF2_SALT_BYTES)
    derived = hashlib.pbkdf2_hmac(
        PBKDF2_ALGORITHM,
        api_key.encode("utf-8"),
        salt,
        PBKDF2_ITERATIONS,
    )
    return (
        f"pbkdf2_{PBKDF2_ALGORITHM}"
        f"${PBKDF2_ITERATIONS}"
        f"${salt.hex()}"
        f"${derived.hex()}"
    )


def verify_api_key(api_key: str, stored_hash: str) -> bool:
    try:
        algorithm, iterations, salt_hex, derived_hex = stored_hash.split("$")
        if algorithm != f"pbkdf2_{PBKDF2_ALGORITHM}":
            return False
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(derived_hex)
        derived = hashlib.pbkdf2_hmac(
            PBKDF2_ALGORITHM,
            api_key.encode("utf-8"),
            salt,
            int(iterations),
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(derived, expected)


def _extract_agent_id_from_api_key(api_key: str) -> str | None:
    agent_id, separator, _ = api_key.partition(".")
    if separator != "." or not agent_id:
        return None
    return agent_id


async def _best_effort_agent_auth_audit(
    request: Request,
    db: Session,
    *,
    agent_id: str | None,
    error_hint: str,
) -> None:
    """
    Best-effort auditing for agent auth failure paths.

    Rationale: 401 failures can be high-volume and should not be able to turn into 500s
    if the audit insert/commit fails (transient DB/pool issues).
    """

    try:
        body_bytes = await request.body()
    except Exception:
        body_bytes = b""

    body_hash = hash_body(body_bytes)
    request_id = request.headers.get("X-Request-ID") or str(uuid4())
    idempotency_key = request.headers.get("Idempotency-Key")

    try:
        record_audit(
            db,
            actor_type="agent",
            agent_id=agent_id,
            method=request.method,
            path=request.url.path,
            idempotency_key=idempotency_key,
            body_hash=body_hash,
            signature_status="none",
            request_id=request_id,
            error_hint=error_hint,
        )
    except Exception as exc:
        # Keep the session usable for the rest of the request lifecycle.
        try:
            db.rollback()
        except Exception:
            pass
        logger.warning("agent auth audit failed: %s", exc)


async def require_agent_api_key(
    *,
    request: Request,
    api_key: str | None = Header(None, alias="X-API-Key"),
    db: Session = Depends(get_db),
) -> Agent:
    if not api_key:
        await _best_effort_agent_auth_audit(
            request,
            db,
            agent_id=None,
            error_hint="missing_agent_api_key",
        )
        raise HTTPException(status_code=401, detail="Invalid agent credentials.")

    agent_id = _extract_agent_id_from_api_key(api_key)
    if not agent_id:
        await _best_effort_agent_auth_audit(
            request,
            db,
            agent_id=None,
            error_hint="invalid_agent_api_key_format",
        )
        raise HTTPException(status_code=401, detail="Invalid agent credentials.")

    agent = db.query(Agent).filter(Agent.agent_id == agent_id).first()
    if agent is None or agent.revoked_at is not None:
        await _best_effort_agent_auth_audit(
            request,
            db,
            agent_id=agent_id,
            error_hint="invalid_or_revoked_agent",
        )
        raise HTTPException(status_code=401, detail="Invalid agent credentials.")
    if not verify_api_key(api_key, agent.api_key_hash):
        await _best_effort_agent_auth_audit(
            request,
            db,
            agent_id=agent_id,
            error_hint="invalid_agent_api_key_hash",
        )
        raise HTTPException(status_code=401, detail="Invalid agent credentials.")
    return agent


def hash_body(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def verify_hmac_v1(secret: str, timestamp: str, body_hash: str, signature: str) -> bool:
    message = f"{timestamp}.{body_hash}".encode("utf-8")
    computed = hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()
    return hmac.compare_digest(computed, signature)


def build_oracle_hmac_v2_payload(
    timestamp: str,
    request_id: str,
    method: str,
    path: str,
    body_hash: str,
) -> str:
    return f"{timestamp}.{request_id}.{method.upper()}.{path}.{body_hash}"


def verify_oracle_hmac_v2(secret: str, payload: str, signature: str) -> bool:
    message = payload.encode("utf-8")
    computed = hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()
    return hmac.compare_digest(computed, signature)


def verify_hmac_v2(
    secret: str,
    timestamp: str,
    request_id: str,
    body_hash: str,
    signature: str,
    *,
    method: str | None = None,
    path: str | None = None,
) -> bool:
    """Backward-compatible wrapper around Oracle HMAC v2 verification."""

    payload = build_oracle_hmac_v2_payload(
        timestamp,
        request_id,
        method or "",
        path or "",
        body_hash,
    )
    return verify_oracle_hmac_v2(secret, payload, signature)
