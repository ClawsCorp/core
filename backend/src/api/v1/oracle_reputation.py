from __future__ import annotations

import hashlib
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from src.core.audit import record_audit
from src.core.database import get_db
from src.core.db_utils import insert_or_get_by_unique
from src.models.agent import Agent
from src.models.indexer_cursor import IndexerCursor
from src.models.observed_customer_referral import ObservedCustomerReferral
from src.models.observed_customer_referral_decision import ObservedCustomerReferralDecision
from src.models.observed_social_signal import ObservedSocialSignal
from src.models.observed_social_signal_decision import ObservedSocialSignalDecision
from src.models.reputation_event import ReputationEvent
from src.schemas.reputation import (
    ObservedCustomerReferralCreateRequest,
    ObservedCustomerReferralDetailResponse,
    ObservedCustomerReferralPublic,
    ObservedSocialSignalCreateRequest,
    ObservedSocialSignalDetailResponse,
    ObservedSocialSignalPublic,
    ReputationObservedSyncData,
    ReputationObservedSyncResponse,
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


@router.post("/reputation/observed-social-signals", response_model=ObservedSocialSignalDetailResponse)
async def create_observed_social_signal(
    payload: ObservedSocialSignalCreateRequest,
    request: Request,
    _: str = Depends(require_oracle_hmac),
    db: Session = Depends(get_db),
) -> ObservedSocialSignalDetailResponse:
    request_id = request.headers.get("X-Request-Id") or str(uuid4())
    body_hash = request.state.body_hash
    signature_status = getattr(request.state, "signature_status", "invalid")

    try:
        agent_db_id = _resolve_optional_agent_db_id(db, payload.agent_id)
    except HTTPException:
        _record_oracle_audit(
            request=request,
            db=db,
            body_hash=body_hash,
            request_id=request_id,
            idempotency_key=payload.idempotency_key,
            signature_status=signature_status,
        )
        raise
    row = ObservedSocialSignal(
        signal_id=str(uuid4()),
        idempotency_key=payload.idempotency_key,
        agent_id=agent_db_id,
        platform=payload.platform,
        signal_url=payload.signal_url,
        account_handle=payload.account_handle,
        content_hash=payload.content_hash,
        note=payload.note,
    )
    row, _created = insert_or_get_by_unique(
        db,
        instance=row,
        model=ObservedSocialSignal,
        unique_filter={"idempotency_key": payload.idempotency_key},
    )
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
    db.refresh(row)
    return ObservedSocialSignalDetailResponse(success=True, data=_observed_social_signal_public(db, row))


@router.post("/reputation/observed-customer-referrals", response_model=ObservedCustomerReferralDetailResponse)
async def create_observed_customer_referral(
    payload: ObservedCustomerReferralCreateRequest,
    request: Request,
    _: str = Depends(require_oracle_hmac),
    db: Session = Depends(get_db),
) -> ObservedCustomerReferralDetailResponse:
    request_id = request.headers.get("X-Request-Id") or str(uuid4())
    body_hash = request.state.body_hash
    signature_status = getattr(request.state, "signature_status", "invalid")

    try:
        agent_db_id = _resolve_optional_agent_db_id(db, payload.agent_id)
    except HTTPException:
        _record_oracle_audit(
            request=request,
            db=db,
            body_hash=body_hash,
            request_id=request_id,
            idempotency_key=payload.idempotency_key,
            signature_status=signature_status,
        )
        raise
    row = ObservedCustomerReferral(
        referral_event_id=str(uuid4()),
        idempotency_key=payload.idempotency_key,
        agent_id=agent_db_id,
        source_system=payload.source_system,
        external_ref=payload.external_ref,
        stage=payload.stage,
        evidence_url=payload.evidence_url,
        note=payload.note,
    )
    row, _created = insert_or_get_by_unique(
        db,
        instance=row,
        model=ObservedCustomerReferral,
        unique_filter={"idempotency_key": payload.idempotency_key},
    )
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
    db.refresh(row)
    return ObservedCustomerReferralDetailResponse(success=True, data=_observed_customer_referral_public(db, row))


@router.post("/reputation/social-signals/sync", response_model=ReputationObservedSyncResponse)
async def sync_observed_social_signals(
    request: Request,
    _: str = Depends(require_oracle_hmac),
    db: Session = Depends(get_db),
) -> ReputationObservedSyncResponse:
    request_id = request.headers.get("X-Request-Id") or str(uuid4())
    body_hash = request.state.body_hash
    signature_status = getattr(request.state, "signature_status", "invalid")

    rows = (
        db.query(ObservedSocialSignal)
        .filter(ObservedSocialSignal.id > _get_reputation_sync_cursor(db, "observed_social_signals"))
        .order_by(ObservedSocialSignal.id.asc())
        .limit(500)
        .all()
    )
    seen = len(rows)
    eligible = 0
    created = 0
    skipped_unattributed = 0
    skipped_missing_identity = 0
    skipped_duplicate_identity = 0

    for row in rows:
        identity_key = _social_signal_identity_key(row)
        if row.agent_id is None:
            skipped_unattributed += 1
            _record_social_signal_decision(
                db,
                row=row,
                decision_status="skipped",
                reason_code="unattributed",
                identity_key=identity_key,
                note="agent_id missing",
            )
            continue
        if not identity_key:
            skipped_missing_identity += 1
            _record_social_signal_decision(
                db,
                row=row,
                decision_status="skipped",
                reason_code="missing_identity",
                identity_key=None,
                note="signal has no usable identity",
            )
            continue
        if _social_signal_identity_already_promoted(db, identity_key):
            skipped_duplicate_identity += 1
            _record_social_signal_decision(
                db,
                row=row,
                decision_status="skipped",
                reason_code="duplicate_identity",
                identity_key=identity_key,
                note="identity already promoted",
            )
            continue
        agent = db.query(Agent).filter(Agent.id == int(row.agent_id)).first()
        if agent is None:
            skipped_unattributed += 1
            _record_social_signal_decision(
                db,
                row=row,
                decision_status="skipped",
                reason_code="unattributed",
                identity_key=identity_key,
                note="agent lookup failed",
            )
            continue
        eligible += 1
        rep_payload = ReputationEventCreateRequest(
            event_id=str(uuid4()),
            idempotency_key=f"rep:social_signal_verified:observed:{row.signal_id}",
            agent_id=agent.agent_id,
            delta_points=SOCIAL_SIGNAL_VERIFIED_POINTS,
            source="social_signal_verified",
            ref_type="social_signal",
            ref_id=_build_social_signal_observed_ref_id(row),
            note=_build_structured_note(
                [
                    f"platform:{row.platform}",
                    f"url:{row.signal_url}" if row.signal_url else "",
                    f"handle:{row.account_handle}" if row.account_handle else "",
                    f"observed_signal_id:{row.signal_id}",
                    row.note or "",
                ]
            ),
        )
        created_now, event = _try_ingest_reputation_event(db, rep_payload)
        if created_now:
            created += 1
            _record_social_signal_decision(
                db,
                row=row,
                decision_status="promoted",
                reason_code=None,
                identity_key=identity_key,
                reputation_event_id=int(event.id),
                note=f"promoted:{event.event_id}",
            )
        else:
            skipped_duplicate_identity += 1
            _record_social_signal_decision(
                db,
                row=row,
                decision_status="skipped",
                reason_code="duplicate_identity",
                identity_key=identity_key,
                reputation_event_id=int(event.id),
                note="reputation event already existed",
            )

    _advance_reputation_sync_cursor(
        db,
        "observed_social_signals",
        rows[-1].id if rows else None,
    )

    _record_oracle_audit(
        request=request,
        db=db,
        body_hash=body_hash,
        request_id=request_id,
        idempotency_key=request.headers.get("Idempotency-Key") or f"rep:sync:social:{request_id}",
        signature_status=signature_status,
        commit=False,
    )
    db.commit()
    return ReputationObservedSyncResponse(
        success=True,
        data=ReputationObservedSyncData(
            candidates_seen=seen,
            eligible_candidates=eligible,
            reputation_events_created=created,
            skipped_unattributed=skipped_unattributed,
            skipped_ineligible_stage=0,
            skipped_missing_identity=skipped_missing_identity,
            skipped_duplicate_identity=skipped_duplicate_identity,
        ),
    )


@router.post("/reputation/customer-referrals/sync", response_model=ReputationObservedSyncResponse)
async def sync_observed_customer_referrals(
    request: Request,
    _: str = Depends(require_oracle_hmac),
    db: Session = Depends(get_db),
) -> ReputationObservedSyncResponse:
    request_id = request.headers.get("X-Request-Id") or str(uuid4())
    body_hash = request.state.body_hash
    signature_status = getattr(request.state, "signature_status", "invalid")

    rows = (
        db.query(ObservedCustomerReferral)
        .filter(ObservedCustomerReferral.id > _get_reputation_sync_cursor(db, "observed_customer_referrals"))
        .order_by(ObservedCustomerReferral.id.asc())
        .limit(500)
        .all()
    )
    seen = len(rows)
    eligible = 0
    created = 0
    skipped_unattributed = 0
    skipped_ineligible_stage = 0
    skipped_duplicate_identity = 0

    for row in rows:
        identity_key = _customer_referral_identity_key(row)
        if row.agent_id is None:
            skipped_unattributed += 1
            _record_customer_referral_decision(
                db,
                row=row,
                decision_status="skipped",
                reason_code="unattributed",
                identity_key=identity_key,
                note="agent_id missing",
            )
            continue
        if row.stage not in {"verified_lead", "paid_conversion"}:
            skipped_ineligible_stage += 1
            _record_customer_referral_decision(
                db,
                row=row,
                decision_status="skipped",
                reason_code="ineligible_stage",
                identity_key=identity_key,
                note=f"stage:{row.stage}",
            )
            continue
        if _customer_referral_identity_already_promoted(db, identity_key):
            skipped_duplicate_identity += 1
            _record_customer_referral_decision(
                db,
                row=row,
                decision_status="skipped",
                reason_code="duplicate_identity",
                identity_key=identity_key,
                note="identity already promoted",
            )
            continue
        agent = db.query(Agent).filter(Agent.id == int(row.agent_id)).first()
        if agent is None:
            skipped_unattributed += 1
            _record_customer_referral_decision(
                db,
                row=row,
                decision_status="skipped",
                reason_code="unattributed",
                identity_key=identity_key,
                note="agent lookup failed",
            )
            continue
        eligible += 1
        delta_points = (
            CUSTOMER_REFERRAL_PAID_POINTS
            if row.stage == "paid_conversion"
            else CUSTOMER_REFERRAL_VERIFIED_POINTS
        )
        rep_payload = ReputationEventCreateRequest(
            event_id=str(uuid4()),
            idempotency_key=f"rep:customer_referral_verified:observed:{row.referral_event_id}:{row.stage}",
            agent_id=agent.agent_id,
            delta_points=delta_points,
            source="customer_referral_verified",
            ref_type="customer_referral",
            ref_id=row.external_ref,
            note=_build_structured_note(
                [
                    f"stage:{row.stage}",
                    f"source_system:{row.source_system}",
                    f"evidence_url:{row.evidence_url}" if row.evidence_url else "",
                    f"observed_referral_id:{row.referral_event_id}",
                    row.note or "",
                ]
            ),
        )
        created_now, event = _try_ingest_reputation_event(db, rep_payload)
        if created_now:
            created += 1
            _record_customer_referral_decision(
                db,
                row=row,
                decision_status="promoted",
                reason_code=None,
                identity_key=identity_key,
                reputation_event_id=int(event.id),
                note=f"promoted:{event.event_id}",
            )
        else:
            skipped_duplicate_identity += 1
            _record_customer_referral_decision(
                db,
                row=row,
                decision_status="skipped",
                reason_code="duplicate_identity",
                identity_key=identity_key,
                reputation_event_id=int(event.id),
                note="reputation event already existed",
            )

    _advance_reputation_sync_cursor(
        db,
        "observed_customer_referrals",
        rows[-1].id if rows else None,
    )

    _record_oracle_audit(
        request=request,
        db=db,
        body_hash=body_hash,
        request_id=request_id,
        idempotency_key=request.headers.get("Idempotency-Key") or f"rep:sync:referrals:{request_id}",
        signature_status=signature_status,
        commit=False,
    )
    db.commit()
    return ReputationObservedSyncResponse(
        success=True,
        data=ReputationObservedSyncData(
            candidates_seen=seen,
            eligible_candidates=eligible,
            reputation_events_created=created,
            skipped_unattributed=skipped_unattributed,
            skipped_ineligible_stage=skipped_ineligible_stage,
            skipped_missing_identity=0,
            skipped_duplicate_identity=skipped_duplicate_identity,
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


def _build_social_signal_observed_ref_id(row: ObservedSocialSignal) -> str:
    candidate = str(row.signal_url or row.account_handle or row.platform or "").strip()
    if len(candidate) <= 128:
        return candidate
    digest = hashlib.sha256(candidate.encode("utf-8")).hexdigest()
    return f"url_sha256:{digest}"


def _try_ingest_reputation_event(db: Session, payload: ReputationEventCreateRequest) -> tuple[bool, ReputationEvent]:
    event, _public_agent_id = ingest_reputation_event(db, payload)
    created = event.idempotency_key == payload.idempotency_key and event.event_id == payload.event_id
    return created, event


def _get_reputation_sync_cursor(db: Session, cursor_key: str) -> int:
    row = (
        db.query(IndexerCursor)
        .filter(IndexerCursor.cursor_key == cursor_key, IndexerCursor.chain_id == 0)
        .first()
    )
    if row is None:
        row, _created = insert_or_get_by_unique(
            db,
            instance=IndexerCursor(cursor_key=cursor_key, chain_id=0, last_block_number=0),
            model=IndexerCursor,
            unique_filter={"cursor_key": cursor_key, "chain_id": 0},
        )
        return int(row.last_block_number or 0)
    return int(row.last_block_number or 0)


def _advance_reputation_sync_cursor(db: Session, cursor_key: str, last_processed_id: int | None) -> None:
    if last_processed_id is None:
        return
    row = (
        db.query(IndexerCursor)
        .filter(IndexerCursor.cursor_key == cursor_key, IndexerCursor.chain_id == 0)
        .first()
    )
    if row is None:
        row = IndexerCursor(cursor_key=cursor_key, chain_id=0, last_block_number=int(last_processed_id))
        db.add(row)
    else:
        row.last_block_number = int(last_processed_id)
    db.flush()


def _social_signal_identity_key(row: ObservedSocialSignal) -> str | None:
    if row.content_hash:
        return _bounded_identity_key("content_hash", row.platform, row.content_hash)
    if row.signal_url:
        return _bounded_identity_key("signal_url", row.platform, row.signal_url)
    if row.account_handle:
        return _bounded_identity_key("account_handle", row.platform, row.account_handle)
    return None


def _customer_referral_identity_key(row: ObservedCustomerReferral) -> str:
    return _bounded_identity_key("customer_referral", row.source_system, row.external_ref, row.stage)


def _bounded_identity_key(prefix: str, *parts: str) -> str:
    joined = ":".join(str(part or "").strip() for part in parts)
    candidate = f"{prefix}:{joined}"
    if len(candidate) <= 128:
        return candidate
    digest = hashlib.sha256(candidate.encode("utf-8")).hexdigest()
    return f"{prefix}:sha256:{digest}"


def _social_signal_identity_already_promoted(db: Session, identity_key: str) -> bool:
    return (
        db.query(ObservedSocialSignalDecision.id)
        .filter(
            ObservedSocialSignalDecision.identity_key == identity_key,
            ObservedSocialSignalDecision.decision_status == "promoted",
        )
        .first()
        is not None
    )


def _customer_referral_identity_already_promoted(db: Session, identity_key: str) -> bool:
    return (
        db.query(ObservedCustomerReferralDecision.id)
        .filter(
            ObservedCustomerReferralDecision.identity_key == identity_key,
            ObservedCustomerReferralDecision.decision_status == "promoted",
        )
        .first()
        is not None
    )


def _record_social_signal_decision(
    db: Session,
    *,
    row: ObservedSocialSignal,
    decision_status: str,
    reason_code: str | None,
    identity_key: str | None,
    reputation_event_id: int | None = None,
    note: str | None = None,
) -> None:
    decision_key = f"obs_social_decision:{row.signal_id}:{decision_status}:{reason_code or 'ok'}"
    decision = ObservedSocialSignalDecision(
        decision_id=str(uuid4()),
        decision_key=decision_key,
        observed_social_signal_id=int(row.id),
        decision_status=decision_status,
        reason_code=reason_code,
        identity_key=identity_key,
        reputation_event_id=reputation_event_id,
        note=_build_structured_note([note or ""]),
    )
    insert_or_get_by_unique(
        db,
        instance=decision,
        model=ObservedSocialSignalDecision,
        unique_filter={"decision_key": decision_key},
    )


def _record_customer_referral_decision(
    db: Session,
    *,
    row: ObservedCustomerReferral,
    decision_status: str,
    reason_code: str | None,
    identity_key: str | None,
    reputation_event_id: int | None = None,
    note: str | None = None,
) -> None:
    decision_key = f"obs_customer_referral_decision:{row.referral_event_id}:{decision_status}:{reason_code or 'ok'}"
    decision = ObservedCustomerReferralDecision(
        decision_id=str(uuid4()),
        decision_key=decision_key,
        observed_customer_referral_id=int(row.id),
        decision_status=decision_status,
        reason_code=reason_code,
        identity_key=identity_key,
        reputation_event_id=reputation_event_id,
        note=_build_structured_note([note or ""]),
    )
    insert_or_get_by_unique(
        db,
        instance=decision,
        model=ObservedCustomerReferralDecision,
        unique_filter={"decision_key": decision_key},
    )


def _resolve_optional_agent_db_id(db: Session, agent_id: str | None) -> int | None:
    if not agent_id:
        return None
    agent = db.query(Agent).filter(Agent.agent_id == agent_id).first()
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    return int(agent.id)


def _observed_social_signal_public(db: Session, row: ObservedSocialSignal) -> ObservedSocialSignalPublic:
    agent_public_id: str | None = None
    if row.agent_id is not None:
        agent = db.query(Agent).filter(Agent.id == int(row.agent_id)).first()
        agent_public_id = agent.agent_id if agent is not None else None
    return ObservedSocialSignalPublic(
        signal_id=row.signal_id,
        idempotency_key=row.idempotency_key,
        agent_id=agent_public_id,
        platform=row.platform,
        signal_url=row.signal_url,
        account_handle=row.account_handle,
        content_hash=row.content_hash,
        note=row.note,
        observed_at=row.observed_at,
        created_at=row.created_at,
    )


def _observed_customer_referral_public(db: Session, row: ObservedCustomerReferral) -> ObservedCustomerReferralPublic:
    agent_public_id: str | None = None
    if row.agent_id is not None:
        agent = db.query(Agent).filter(Agent.id == int(row.agent_id)).first()
        agent_public_id = agent.agent_id if agent is not None else None
    return ObservedCustomerReferralPublic(
        referral_event_id=row.referral_event_id,
        idempotency_key=row.idempotency_key,
        agent_id=agent_public_id,
        source_system=row.source_system,
        external_ref=row.external_ref,
        stage=row.stage,
        evidence_url=row.evidence_url,
        note=row.note,
        observed_at=row.observed_at,
        created_at=row.created_at,
    )


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
