from __future__ import annotations

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from src.core.config import get_settings
from src.core.database import get_db
from src.core.security import hash_body, verify_api_key, verify_hmac_v1
from src.models.agent import Agent


def require_agent_auth(
    *,
    agent_id: str | None = Header(None, alias="X-Agent-ID"),
    agent_key: str | None = Header(None, alias="X-Agent-Key"),
    db: Session = Depends(get_db),
) -> Agent:
    if not agent_id or not agent_key:
        raise HTTPException(status_code=401, detail="Invalid agent credentials.")
    agent = db.query(Agent).filter(Agent.agent_id == agent_id).first()
    if agent is None or agent.revoked_at is not None:
        raise HTTPException(status_code=401, detail="Invalid agent credentials.")
    if not verify_api_key(agent_key, agent.api_key_hash):
        raise HTTPException(status_code=401, detail="Invalid agent credentials.")
    return agent


async def require_oracle_hmac(request: Request) -> str:
    settings = get_settings()
    timestamp = request.headers.get("X-Request-Timestamp")
    signature = request.headers.get("X-Signature")
    body_bytes = await request.body()
    body_hash = hash_body(body_bytes)
    request.state.body_hash = body_hash

    if not timestamp or not signature:
        request.state.signature_status = "none"
        raise HTTPException(status_code=403, detail="Invalid signature.")

    if not settings.oracle_hmac_secret:
        request.state.signature_status = "invalid"
        raise HTTPException(status_code=403, detail="Invalid signature.")

    if not verify_hmac_v1(settings.oracle_hmac_secret, timestamp, body_hash, signature):
        request.state.signature_status = "invalid"
        raise HTTPException(status_code=403, detail="Invalid signature.")

    request.state.signature_status = "valid"
    return body_hash
