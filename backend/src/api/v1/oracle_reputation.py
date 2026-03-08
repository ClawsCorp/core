from __future__ import annotations

import hashlib
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from src.core.audit import record_audit
from src.core.database import get_db
from src.models.reputation_event import ReputationEvent
from src.schemas.reputation import (
    ReputationCustomerReferralCreateRequest,
    ReputationEventCreateRequest,
    ReputationEventDetailResponse,
    ReputationEventPublic,
    ReputationSocialSignalCreateRequest,
)
from src.api.v1.dependencies import require_oracle_hmac
from src.services.reputation_ingestion import ingest_reputation_event
from src.services.reputation_policy import (
    CUSTOMER_REFERRAL_PAID_POINTS,
    CUSTOMER_REFERRAL_VERIFIED_POINTS,
    SOCIAL_SIGNAL_VERIFIED_POINTS,
)

router = APIRouter(prefix="/api/v1/oracle", tags=["oracle-reputation"])


@router.post("/reputation-events", response_model=ReputationEventDetailResponse)
async def create_reputation_event(
    payload: ReputationEventCreateRequest,
    request: Request,
    _: str = Depends(require_oracle_hmac),
    db: Session = Depends(get_db),
) -> ReputationEventDetailResponse:
    request_id = request.headers.get("X-Request-Id") or str(uuid4())
    body_hash = request.state.body_hash
    signature_status = getattr(request.state, "signature_status", "invalid")

    try:
        event, public_agent_id = ingest_reputation_event(db, payload)
    except ValueError as exc:
        _record_oracle_audit(
            request=request,
            db=db,
            body_hash=body_hash,
            request_id=request_id,
            idempotency_key=payload.idempotency_key,
            signature_status=signature_status,
        )
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LookupError as exc:
        _record_oracle_audit(
            request=request,
            db=db,
            body_hash=body_hash,
            request_id=request_id,
            idempotency_key=payload.idempotency_key,
            signature_status=signature_status,
        )
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    _record_oracle_audit(
        request=request,
        db=db,
        body_hash=body_hash,
        request_id=request_id,
        idempotency_key=payload.idempotency_key,
        signature_status=signature_status,
        commit=False,
    )
    db.commit()
    db.refresh(event)

    return ReputationEventDetailResponse(success=True, data=_public_event(public_agent_id, event))


@router.post("/reputation/social-signals", response_model=ReputationEventDetailResponse)
async def create_social_signal_reputation_event(
    payload: ReputationSocialSignalCreateRequest,
    request: Request,
    _: str = Depends(require_oracle_hmac),
    db: Session = Depends(get_db),
) -> ReputationEventDetailResponse:
    note_parts = [f"platform:{payload.platform}"]
    if payload.account_handle:
        note_parts.append(f"handle:{payload.account_handle}")
    if payload.signal_url:
        note_parts.append(f"url:{payload.signal_url}")
    if payload.note:
        note_parts.append(payload.note)

    return await _create_structured_reputation_event(
        db=db,
        request=request,
        payload=ReputationEventCreateRequest(
            event_id=str(uuid4()),
            idempotency_key=payload.idempotency_key,
            agent_id=payload.agent_id,
            delta_points=SOCIAL_SIGNAL_VERIFIED_POINTS,
            source="social_signal_verified",
            ref_type="social_signal",
            ref_id=_build_social_signal_ref_id(payload),
            note=_build_structured_note(note_parts),
        ),
    )


@router.post("/reputation/customer-referrals", response_model=ReputationEventDetailResponse)
async def create_customer_referral_reputation_event(
    payload: ReputationCustomerReferralCreateRequest,
    request: Request,
    _: str = Depends(require_oracle_hmac),
    db: Session = Depends(get_db),
) -> ReputationEventDetailResponse:
    delta_points = (
        CUSTOMER_REFERRAL_PAID_POINTS
        if payload.stage == "paid_conversion"
        else CUSTOMER_REFERRAL_VERIFIED_POINTS
    )
    note_parts = [f"stage:{payload.stage}"]
    if payload.evidence_url:
        note_parts.append(f"url:{payload.evidence_url}")
    if payload.note:
        note_parts.append(payload.note)

    return await _create_structured_reputation_event(
        db=db,
        request=request,
        payload=ReputationEventCreateRequest(
            event_id=str(uuid4()),
            idempotency_key=payload.idempotency_key,
            agent_id=payload.agent_id,
            delta_points=delta_points,
            source="customer_referral_verified",
            ref_type="customer_referral",
            ref_id=payload.referral_id,
            note=_build_structured_note(note_parts),
        ),
    )


def _record_oracle_audit(
    request: Request,
    db: Session,
    body_hash: str,
    request_id: str,
    idempotency_key: str,
    signature_status: str,
    commit: bool = True,
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
        request_id=request_id,
        commit=commit,
    )


def _build_social_signal_ref_id(payload: ReputationSocialSignalCreateRequest) -> str:
    candidate = str(payload.signal_url or payload.account_handle or payload.platform or "").strip()
    if len(candidate) <= 128:
        return candidate
    digest = hashlib.sha256(candidate.encode("utf-8")).hexdigest()
    return f"url_sha256:{digest}"


def _build_structured_note(parts: list[str]) -> str | None:
    joined = ";".join(part for part in parts if part)
    if not joined:
        return None
    if len(joined) <= 255:
        return joined
    digest = hashlib.sha256(joined.encode("utf-8")).hexdigest()[:16]
    return f"{joined[:230]};sha256:{digest}"


async def _create_structured_reputation_event(
    *,
    db: Session,
    request: Request,
    payload: ReputationEventCreateRequest,
) -> ReputationEventDetailResponse:
    request_id = request.headers.get("X-Request-Id") or str(uuid4())
    body_hash = request.state.body_hash
    signature_status = getattr(request.state, "signature_status", "invalid")

    try:
        event, public_agent_id = ingest_reputation_event(db, payload)
    except ValueError as exc:
        _record_oracle_audit(
            request=request,
            db=db,
            body_hash=body_hash,
            request_id=request_id,
            idempotency_key=payload.idempotency_key,
            signature_status=signature_status,
        )
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LookupError as exc:
        _record_oracle_audit(
            request=request,
            db=db,
            body_hash=body_hash,
            request_id=request_id,
            idempotency_key=payload.idempotency_key,
            signature_status=signature_status,
        )
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    _record_oracle_audit(
        request=request,
        db=db,
        body_hash=body_hash,
        request_id=request_id,
        idempotency_key=payload.idempotency_key,
        signature_status=signature_status,
        commit=False,
    )
    db.commit()
    db.refresh(event)
    return ReputationEventDetailResponse(success=True, data=_public_event(public_agent_id, event))


def _public_event(agent_id: str, event: ReputationEvent) -> ReputationEventPublic:
    return ReputationEventPublic(
        event_id=event.event_id,
        idempotency_key=event.idempotency_key,
        agent_id=agent_id,
        delta_points=event.delta_points,
        source=event.source,
        ref_type=event.ref_type,
        ref_id=event.ref_id,
        note=event.note,
        created_at=event.created_at,
    )
