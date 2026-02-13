from __future__ import annotations

import hashlib
import hmac
import secrets
from typing import Final

from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from src.core.database import get_db
from src.models.agent import Agent

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


def require_agent_api_key(
    *,
    api_key: str | None = Header(None, alias="X-API-Key"),
    db: Session = Depends(get_db),
) -> Agent:
    if not api_key:
        raise HTTPException(status_code=401, detail="Invalid agent credentials.")

    agent_id = _extract_agent_id_from_api_key(api_key)
    if not agent_id:
        raise HTTPException(status_code=401, detail="Invalid agent credentials.")

    agent = db.query(Agent).filter(Agent.agent_id == agent_id).first()
    if agent is None or agent.revoked_at is not None:
        raise HTTPException(status_code=401, detail="Invalid agent credentials.")
    if not verify_api_key(api_key, agent.api_key_hash):
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
    body_hash: str,
    *,
    method: str | None = None,
    path: str | None = None,
) -> str:
    normalized_method = (method or "").upper()
    normalized_path = path or ""
    return f"{timestamp}.{request_id}.{normalized_method}.{normalized_path}.{body_hash}"


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
    message = build_oracle_hmac_v2_payload(
        timestamp,
        request_id,
        body_hash,
        method=method,
        path=path,
    ).encode("utf-8")
    computed = hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()
    return hmac.compare_digest(computed, signature)
