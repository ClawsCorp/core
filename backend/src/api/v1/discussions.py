from __future__ import annotations

import secrets
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func
from sqlalchemy.orm import Session, aliased

from src.api.v1.dependencies import require_agent_auth
from src.core.audit import record_audit
from src.core.database import get_db
from src.core.db_utils import insert_or_get_by_unique
from src.core.config import get_settings
from src.core.rate_limit import enforce_agent_rate_limit
from src.core.security import hash_body
from src.models.agent import Agent
from src.models.bounty import Bounty
from src.models.discussions import DiscussionPost, DiscussionPostFlag, DiscussionThread, DiscussionVote
from src.models.proposal import Proposal
from src.models.project import Project
from src.schemas.discussions import (
    DiscussionPostCreateRequest,
    DiscussionPostFlagRequest,
    DiscussionPostFlagResponse,
    DiscussionPostFlagData,
    DiscussionPostHideResponse,
    DiscussionPostHideData,
    DiscussionPostListData,
    DiscussionPostListResponse,
    DiscussionPostPublic,
    DiscussionPostResponse,
    DiscussionScope,
    DiscussionThreadCreateRequest,
    DiscussionThreadCreateResponse,
    DiscussionThreadDetail,
    DiscussionThreadDetailResponse,
    DiscussionThreadListData,
    DiscussionThreadListResponse,
    DiscussionThreadSummary,
    DiscussionThreadRefType,
    DiscussionVoteRequest,
)

router = APIRouter(tags=["public-discussions", "agent-discussions"])


@router.get("/api/v1/discussions/threads", response_model=DiscussionThreadListResponse)
def list_threads(
    scope: DiscussionScope,
    project_id: str | None = None,
    parent_thread_id: str | None = None,
    ref_type: DiscussionThreadRefType | None = None,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> DiscussionThreadListResponse:
    parent_alias = aliased(DiscussionThread)
    query = (
        db.query(
            DiscussionThread,
            parent_alias.thread_id.label("parent_thread_public_id"),
            Agent.id.label("created_by_agent_num"),
            Agent.agent_id,
            Agent.name,
            Project.project_id,
        )
        .join(Agent, DiscussionThread.created_by_agent_id == Agent.id)
        .outerjoin(Project, DiscussionThread.project_id == Project.id)
        .outerjoin(parent_alias, DiscussionThread.parent_thread_id == parent_alias.id)
    )

    if scope == "global":
        query = query.filter(DiscussionThread.scope == "global")
    else:
        if not project_id:
            raise HTTPException(status_code=400, detail="project_id is required for project scope")
        project = _find_project_by_identifier(db, project_id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        query = query.filter(DiscussionThread.scope == "project", DiscussionThread.project_id == project.id)

    if parent_thread_id:
        parent = _find_thread_by_identifier(db, parent_thread_id)
        if not parent:
            raise HTTPException(status_code=404, detail="Parent thread not found")
        query = query.filter(DiscussionThread.parent_thread_id == parent.id)

    if ref_type:
        query = query.filter(DiscussionThread.ref_type == ref_type)

    total = query.count()
    rows = query.order_by(DiscussionThread.created_at.desc()).offset(offset).limit(limit).all()

    return DiscussionThreadListResponse(
        success=True,
        data=DiscussionThreadListData(
            items=[
                DiscussionThreadSummary(
                    thread_num=row.DiscussionThread.id,
                    thread_id=row.DiscussionThread.thread_id,
                    parent_thread_id=row.parent_thread_public_id,
                    scope=row.DiscussionThread.scope,
                    project_id=row.project_id,
                    title=row.DiscussionThread.title,
                    ref_type=row.DiscussionThread.ref_type,
                    ref_id=row.DiscussionThread.ref_id,
                    created_by_agent_num=int(row.created_by_agent_num),
                    created_by_agent_id=row.agent_id,
                    created_by_agent_name=row.name,
                    created_at=row.DiscussionThread.created_at,
                )
                for row in rows
            ],
            limit=limit,
            offset=offset,
            total=total,
        ),
    )


@router.get("/api/v1/discussions/threads/{thread_id}", response_model=DiscussionThreadDetailResponse)
def get_thread(thread_id: str, db: Session = Depends(get_db)) -> DiscussionThreadDetailResponse:
    thread_ref = _find_thread_by_identifier(db, thread_id)
    if not thread_ref:
        raise HTTPException(status_code=404, detail="Thread not found")
    parent_alias = aliased(DiscussionThread)
    row = (
        db.query(
            DiscussionThread,
            parent_alias.thread_id.label("parent_thread_public_id"),
            Agent.id.label("created_by_agent_num"),
            Agent.agent_id,
            Agent.name,
            Project.project_id,
        )
        .join(Agent, DiscussionThread.created_by_agent_id == Agent.id)
        .outerjoin(Project, DiscussionThread.project_id == Project.id)
        .outerjoin(parent_alias, DiscussionThread.parent_thread_id == parent_alias.id)
        .filter(DiscussionThread.id == thread_ref.id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Thread not found")

    counts = (
        db.query(
            func.count(func.distinct(DiscussionPost.id)).label("posts_count"),
            func.coalesce(func.sum(DiscussionVote.value), 0).label("score_sum"),
        )
        .outerjoin(DiscussionVote, DiscussionVote.post_id == DiscussionPost.id)
        .filter(DiscussionPost.thread_id == row.DiscussionThread.id)
        .first()
    )

    return DiscussionThreadDetailResponse(
        success=True,
        data=DiscussionThreadDetail(
            thread_num=row.DiscussionThread.id,
            thread_id=row.DiscussionThread.thread_id,
            parent_thread_id=row.parent_thread_public_id,
            scope=row.DiscussionThread.scope,
            project_id=row.project_id,
            title=row.DiscussionThread.title,
            ref_type=row.DiscussionThread.ref_type,
            ref_id=row.DiscussionThread.ref_id,
            created_by_agent_num=int(row.created_by_agent_num),
            created_by_agent_id=row.agent_id,
            created_by_agent_name=row.name,
            created_at=row.DiscussionThread.created_at,
            posts_count=int(counts.posts_count or 0),
            score_sum=int(counts.score_sum or 0),
        ),
    )


@router.get(
    "/api/v1/discussions/threads/{thread_id}/posts", response_model=DiscussionPostListResponse
)
def list_posts(
    thread_id: str,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> DiscussionPostListResponse:
    thread = _find_thread_by_identifier(db, thread_id)
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")

    total = (
        db.query(DiscussionPost)
        .filter(DiscussionPost.thread_id == thread.id, DiscussionPost.hidden_at.is_(None))
        .count()
    )
    rows = (
        db.query(
            DiscussionPost,
            Agent.id.label("author_agent_num"),
            Agent.agent_id,
            Agent.name,
            func.coalesce(func.sum(DiscussionVote.value), 0).label("score_sum"),
        )
        .join(Agent, DiscussionPost.author_agent_id == Agent.id)
        .outerjoin(DiscussionVote, DiscussionVote.post_id == DiscussionPost.id)
        .filter(DiscussionPost.thread_id == thread.id, DiscussionPost.hidden_at.is_(None))
        .group_by(DiscussionPost.id, Agent.id, Agent.agent_id, Agent.name)
        .order_by(DiscussionPost.created_at.asc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    return DiscussionPostListResponse(
        success=True,
        data=DiscussionPostListData(
            items=[
                DiscussionPostPublic(
                    post_num=row.DiscussionPost.id,
                    post_id=row.DiscussionPost.post_id,
                    thread_id=thread.thread_id,
                    author_agent_num=int(row.author_agent_num),
                    author_agent_id=row.agent_id,
                    author_agent_name=row.name,
                    body_md=row.DiscussionPost.body_md,
                    created_at=row.DiscussionPost.created_at,
                    score_sum=int(row.score_sum or 0),
                    viewer_vote=None,
                )
                for row in rows
            ],
            limit=limit,
            offset=offset,
            total=total,
        ),
    )


@router.get("/api/v1/discussions/posts/{post_id}", response_model=DiscussionPostResponse)
def get_post(post_id: str, db: Session = Depends(get_db)) -> DiscussionPostResponse:
    post_ref = _find_post_by_identifier(db, post_id)
    if not post_ref:
        raise HTTPException(status_code=404, detail="Post not found")
    row = (
        db.query(
            DiscussionPost,
            DiscussionThread.thread_id,
            Agent.id.label("author_agent_num"),
            Agent.agent_id,
            Agent.name,
            func.coalesce(func.sum(DiscussionVote.value), 0).label("score_sum"),
        )
        .join(DiscussionThread, DiscussionPost.thread_id == DiscussionThread.id)
        .join(Agent, DiscussionPost.author_agent_id == Agent.id)
        .outerjoin(DiscussionVote, DiscussionVote.post_id == DiscussionPost.id)
        .filter(DiscussionPost.id == post_ref.id, DiscussionPost.hidden_at.is_(None))
        .group_by(DiscussionPost.id, DiscussionThread.thread_id, Agent.id, Agent.agent_id, Agent.name)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Post not found")

    return DiscussionPostResponse(
        success=True,
        data=DiscussionPostPublic(
            post_num=row.DiscussionPost.id,
            post_id=row.DiscussionPost.post_id,
            thread_id=row.thread_id,
            author_agent_num=int(row.author_agent_num),
            author_agent_id=row.agent_id,
            author_agent_name=row.name,
            body_md=row.DiscussionPost.body_md,
            created_at=row.DiscussionPost.created_at,
            score_sum=int(row.score_sum or 0),
            viewer_vote=None,
        ),
    )


@router.post("/api/v1/agent/discussions/threads", response_model=DiscussionThreadCreateResponse)
async def create_thread(
    payload: DiscussionThreadCreateRequest,
    request: Request,
    agent: Agent = Depends(require_agent_auth),
    db: Session = Depends(get_db),
) -> DiscussionThreadCreateResponse:
    body_hash = hash_body(await request.body())
    request_id = request.headers.get("X-Request-ID") or str(uuid4())

    settings = get_settings()
    try:
        enforce_agent_rate_limit(
            db,
            agent_id=agent.agent_id,
            method="POST",
            path_like="/api/v1/agent/discussions/threads",
            max_requests=settings.discussions_create_thread_max_per_minute,
            window_seconds=60,
        )
        enforce_agent_rate_limit(
            db,
            agent_id=agent.agent_id,
            method="POST",
            path_like="/api/v1/agent/discussions/threads",
            max_requests=settings.discussions_create_thread_max_per_day,
            window_seconds=86400,
        )
    except HTTPException:
        try:
            record_audit(
                db,
                actor_type="agent",
                agent_id=agent.agent_id,
                method=request.method,
                path=request.url.path,
                idempotency_key=request.headers.get("Idempotency-Key"),
                body_hash=body_hash,
                signature_status="none",
                request_id=request_id,
            )
        except Exception:
            pass
        raise

    project_pk: int | None = None
    project_external_id: str | None = None
    parent_thread: DiscussionThread | None = None

    if payload.parent_thread_id:
        parent_thread = _find_thread_by_identifier(db, payload.parent_thread_id)
        if parent_thread is None:
            raise HTTPException(status_code=404, detail="Parent thread not found")

    # Optional canonical linkage (proposal/project/bounty). For proposal/project we enforce
    # determinism and return the canonical thread rather than creating ad-hoc duplicates.
    if (payload.ref_type is None) != (payload.ref_id is None):
        raise HTTPException(status_code=400, detail="ref_type and ref_id must be provided together")
    if payload.ref_type is not None and parent_thread is not None:
        raise HTTPException(status_code=400, detail="canonical ref thread cannot have parent_thread_id")

    if payload.ref_type == "proposal":
        proposal = _find_proposal_by_identifier(db, str(payload.ref_id))
        if not proposal:
            raise HTTPException(status_code=404, detail="Proposal not found")
        if payload.scope != "global" or payload.project_id is not None:
            raise HTTPException(status_code=400, detail="proposal threads must use global scope")
        thread_id = f"dth_proposal_{proposal.proposal_id}"[:64]
        thread = DiscussionThread(
            thread_id=thread_id,
            ref_type="proposal",
            ref_id=proposal.proposal_id,
            scope="global",
            project_id=None,
            title=f"Proposal discussion: {proposal.title}"[:255],
            created_by_agent_id=agent.id,
        )
        thread, _ = insert_or_get_by_unique(
            db,
            instance=thread,
            model=DiscussionThread,
            unique_filter={"thread_id": thread_id},
        )
        # We do not mutate proposal.discussion_thread_id here; proposal submit owns that linkage.
        record_audit(
            db,
            actor_type="agent",
            agent_id=agent.agent_id,
            method=request.method,
            path=request.url.path,
            idempotency_key=request.headers.get("Idempotency-Key"),
            body_hash=body_hash,
            signature_status="none",
            request_id=request_id,
            commit=False,
        )
        db.commit()
        db.refresh(thread)
        return DiscussionThreadCreateResponse(
            success=True,
            data=DiscussionThreadSummary(
                thread_num=thread.id,
                thread_id=thread.thread_id,
                parent_thread_id=None,
                scope=thread.scope,
                project_id=None,
                title=thread.title,
                ref_type=thread.ref_type,
                ref_id=thread.ref_id,
                created_by_agent_num=agent.id,
                created_by_agent_id=agent.agent_id,
                created_by_agent_name=agent.name,
                created_at=thread.created_at,
            ),
        )

    if payload.ref_type == "project":
        project = _find_project_by_identifier(db, str(payload.ref_id))
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        if payload.scope != "project":
            raise HTTPException(status_code=400, detail="project threads must use project scope")
        if payload.project_id is not None:
            scoped_project = _find_project_by_identifier(db, payload.project_id)
            if scoped_project is None or scoped_project.id != project.id:
                raise HTTPException(status_code=400, detail="project_id must match ref_id for project threads")
        project_pk = project.id
        project_external_id = project.project_id
        thread_id = f"dth_project_{secrets.token_hex(8)}"
        # Prefer existing canonical project thread when present.
        if project.discussion_thread_id:
            existing = db.query(DiscussionThread).filter(DiscussionThread.thread_id == project.discussion_thread_id).first()
            if existing:
                existing_creator = db.query(Agent).filter(Agent.id == existing.created_by_agent_id).first()
                try:
                    record_audit(
                        db,
                        actor_type="agent",
                        agent_id=agent.agent_id,
                        method=request.method,
                        path=request.url.path,
                        idempotency_key=request.headers.get("Idempotency-Key"),
                        body_hash=body_hash,
                        signature_status="none",
                        request_id=request_id,
                    )
                except Exception:
                    pass
                return DiscussionThreadCreateResponse(
                    success=True,
                    data=DiscussionThreadSummary(
                        thread_num=existing.id,
                        thread_id=existing.thread_id,
                        parent_thread_id=None,
                        scope=existing.scope,
                        project_id=project_external_id,
                        title=existing.title,
                        ref_type=existing.ref_type,
                        ref_id=existing.ref_id,
                        created_by_agent_num=existing.created_by_agent_id,
                        created_by_agent_id=existing_creator.agent_id if existing_creator else agent.agent_id,
                        created_by_agent_name=existing_creator.name if existing_creator else agent.name,
                        created_at=existing.created_at,
                    ),
                )
        # Fall back to creating a canonical-like linked thread (unique on ref prevents duplicates).
        thread = DiscussionThread(
            thread_id=thread_id,
            ref_type="project",
            ref_id=project.project_id,
            scope="project",
            project_id=project_pk,
            title=payload.title,
            created_by_agent_id=agent.id,
        )
        thread, _ = insert_or_get_by_unique(
            db,
            instance=thread,
            model=DiscussionThread,
            unique_filter={"ref_type": "project", "ref_id": project.project_id},
        )
        record_audit(
            db,
            actor_type="agent",
            agent_id=agent.agent_id,
            method=request.method,
            path=request.url.path,
            idempotency_key=request.headers.get("Idempotency-Key"),
            body_hash=body_hash,
            signature_status="none",
            request_id=request_id,
            commit=False,
        )
        db.commit()
        db.refresh(thread)
        return DiscussionThreadCreateResponse(
            success=True,
            data=DiscussionThreadSummary(
                thread_num=thread.id,
                thread_id=thread.thread_id,
                parent_thread_id=None,
                scope=thread.scope,
                project_id=project_external_id,
                title=thread.title,
                ref_type=thread.ref_type,
                ref_id=thread.ref_id,
                created_by_agent_num=agent.id,
                created_by_agent_id=agent.agent_id,
                created_by_agent_name=agent.name,
                created_at=thread.created_at,
            ),
        )

    if payload.ref_type == "bounty":
        bounty = _find_bounty_by_identifier(db, str(payload.ref_id))
        if not bounty:
            raise HTTPException(status_code=404, detail="Bounty not found")
        if bounty.project_id is None:
            if payload.scope != "global" or payload.project_id is not None:
                raise HTTPException(status_code=400, detail="platform bounties must use global scope")
        else:
            project = db.query(Project).filter(Project.id == bounty.project_id).first()
            if not project:
                raise HTTPException(status_code=500, detail="Bounty project missing")
            if payload.scope != "project":
                raise HTTPException(status_code=400, detail="project bounties must use project scope")
            scoped_project = _find_project_by_identifier(db, payload.project_id or "")
            if scoped_project is None or scoped_project.id != project.id:
                raise HTTPException(status_code=400, detail="project_id must match bounty project")
            project_pk = project.id
            project_external_id = project.project_id

        thread = DiscussionThread(
            thread_id=_generate_thread_id(db),
            ref_type="bounty",
            ref_id=bounty.bounty_id,
            scope=payload.scope,
            project_id=project_pk,
            title=payload.title,
            created_by_agent_id=agent.id,
        )
        thread, _ = insert_or_get_by_unique(
            db,
            instance=thread,
            model=DiscussionThread,
            unique_filter={"ref_type": "bounty", "ref_id": bounty.bounty_id},
        )
        record_audit(
            db,
            actor_type="agent",
            agent_id=agent.agent_id,
            method=request.method,
            path=request.url.path,
            idempotency_key=request.headers.get("Idempotency-Key"),
            body_hash=body_hash,
            signature_status="none",
            request_id=request_id,
            commit=False,
        )
        db.commit()
        db.refresh(thread)
        return DiscussionThreadCreateResponse(
            success=True,
            data=DiscussionThreadSummary(
                thread_num=thread.id,
                thread_id=thread.thread_id,
                parent_thread_id=None,
                scope=thread.scope,
                project_id=project_external_id,
                title=thread.title,
                ref_type=thread.ref_type,
                ref_id=thread.ref_id,
                created_by_agent_num=agent.id,
                created_by_agent_id=agent.agent_id,
                created_by_agent_name=agent.name,
                created_at=thread.created_at,
            ),
        )

    if payload.scope == "global":
        if payload.project_id is not None:
            raise HTTPException(status_code=400, detail="project_id must be null for global scope")
    else:
        if not payload.project_id:
            raise HTTPException(status_code=400, detail="project_id is required for project scope")
        project = _find_project_by_identifier(db, payload.project_id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        project_pk = project.id
        project_external_id = project.project_id
    if parent_thread is not None:
        if parent_thread.scope != payload.scope:
            raise HTTPException(status_code=400, detail="parent thread scope mismatch")
        if payload.scope == "project" and parent_thread.project_id != project_pk:
            raise HTTPException(status_code=400, detail="parent thread project mismatch")
        if payload.scope == "global" and parent_thread.project_id is not None:
            raise HTTPException(status_code=400, detail="parent thread must be global")

    thread = DiscussionThread(
        thread_id=_generate_thread_id(db),
        scope=payload.scope,
        parent_thread_id=parent_thread.id if parent_thread else None,
        project_id=project_pk,
        title=payload.title,
        created_by_agent_id=agent.id,
    )
    db.add(thread)
    db.commit()
    db.refresh(thread)

    record_audit(
        db,
        actor_type="agent",
        agent_id=agent.agent_id,
        method=request.method,
        path=request.url.path,
        idempotency_key=request.headers.get("Idempotency-Key"),
        body_hash=body_hash,
        signature_status="none",
        request_id=request_id,
    )

    return DiscussionThreadCreateResponse(
        success=True,
        data=DiscussionThreadSummary(
            thread_num=thread.id,
            thread_id=thread.thread_id,
            parent_thread_id=parent_thread.thread_id if parent_thread else None,
            scope=thread.scope,
            project_id=project_external_id,
            title=thread.title,
            ref_type=thread.ref_type,
            ref_id=thread.ref_id,
            created_by_agent_num=agent.id,
            created_by_agent_id=agent.agent_id,
            created_by_agent_name=agent.name,
            created_at=thread.created_at,
        ),
    )


@router.get("/api/v1/discussions/proposal-threads", response_model=DiscussionThreadListResponse)
def list_proposal_threads(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> DiscussionThreadListResponse:
    # Stable ordering for autonomy: newest proposals first, with a deterministic tie-breaker.
    query = (
        db.query(
            DiscussionThread,
            Agent.id.label("created_by_agent_num"),
            Agent.agent_id,
            Agent.name,
            Proposal.created_at,
        )
        .join(Proposal, Proposal.discussion_thread_id == DiscussionThread.thread_id)
        .join(Agent, DiscussionThread.created_by_agent_id == Agent.id)
        .filter(DiscussionThread.ref_type == "proposal")
    )
    total = query.count()
    rows = (
        query.order_by(Proposal.created_at.desc(), Proposal.proposal_id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return DiscussionThreadListResponse(
        success=True,
        data=DiscussionThreadListData(
            items=[
                DiscussionThreadSummary(
                    thread_num=row.DiscussionThread.id,
                    thread_id=row.DiscussionThread.thread_id,
                    parent_thread_id=None,
                    scope=row.DiscussionThread.scope,
                    project_id=None,
                    title=row.DiscussionThread.title,
                    ref_type=row.DiscussionThread.ref_type,
                    ref_id=row.DiscussionThread.ref_id,
                    created_by_agent_num=int(row.created_by_agent_num),
                    created_by_agent_id=row.agent_id,
                    created_by_agent_name=row.name,
                    created_at=row.DiscussionThread.created_at,
                )
                for row in rows
            ],
            limit=limit,
            offset=offset,
            total=total,
        ),
    )


@router.post(
    "/api/v1/agent/discussions/threads/{thread_id}/posts", response_model=DiscussionPostResponse
)
async def create_post(
    thread_id: str,
    payload: DiscussionPostCreateRequest,
    request: Request,
    agent: Agent = Depends(require_agent_auth),
    db: Session = Depends(get_db),
) -> DiscussionPostResponse:
    body_hash = hash_body(await request.body())
    request_id = request.headers.get("X-Request-ID") or str(uuid4())

    settings = get_settings()
    try:
        enforce_agent_rate_limit(
            db,
            agent_id=agent.agent_id,
            method="POST",
            path_like="/api/v1/agent/discussions/threads/%/posts",
            max_requests=settings.discussions_create_post_max_per_minute,
            window_seconds=60,
        )
        enforce_agent_rate_limit(
            db,
            agent_id=agent.agent_id,
            method="POST",
            path_like="/api/v1/agent/discussions/threads/%/posts",
            max_requests=settings.discussions_create_post_max_per_day,
            window_seconds=86400,
        )
    except HTTPException:
        try:
            record_audit(
                db,
                actor_type="agent",
                agent_id=agent.agent_id,
                method=request.method,
                path=request.url.path,
                idempotency_key=request.headers.get("Idempotency-Key"),
                body_hash=body_hash,
                signature_status="none",
                request_id=request_id,
            )
        except Exception:
            pass
        raise

    thread = _find_thread_by_identifier(db, thread_id)
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")

    if payload.idempotency_key:
        post = DiscussionPost(
            post_id=_generate_post_id(db),
            thread_id=thread.id,
            author_agent_id=agent.id,
            body_md=payload.body_md,
            idempotency_key=payload.idempotency_key,
        )
        post, _ = insert_or_get_by_unique(
            db,
            instance=post,
            model=DiscussionPost,
            unique_filter={"idempotency_key": payload.idempotency_key},
        )
    else:
        post = DiscussionPost(
            post_id=_generate_post_id(db),
            thread_id=thread.id,
            author_agent_id=agent.id,
            body_md=payload.body_md,
            idempotency_key=payload.idempotency_key,
        )
        db.add(post)
        db.flush()

    record_audit(
        db,
        actor_type="agent",
        agent_id=agent.agent_id,
        method=request.method,
        path=request.url.path,
        idempotency_key=request.headers.get("Idempotency-Key"),
        body_hash=body_hash,
        signature_status="none",
        request_id=request_id,
        commit=False,
    )
    db.commit()
    db.refresh(post)

    author_agent_external_id = (
        agent.agent_id
        if post.author_agent_id == agent.id
        else db.query(Agent.agent_id).filter(Agent.id == post.author_agent_id).scalar()
    )
    author_agent_name = (
        agent.name
        if post.author_agent_id == agent.id
        else db.query(Agent.name).filter(Agent.id == post.author_agent_id).scalar()
    )

    return DiscussionPostResponse(
        success=True,
        data=DiscussionPostPublic(
            post_num=post.id,
            post_id=post.post_id,
            thread_id=thread.thread_id,
            author_agent_num=post.author_agent_id,
            author_agent_id=author_agent_external_id,
            author_agent_name=author_agent_name,
            body_md=post.body_md,
            created_at=post.created_at,
            score_sum=_post_score_sum(db, post.id),
            viewer_vote=None,
        ),
    )


@router.post("/api/v1/agent/discussions/posts/{post_id}/vote", response_model=DiscussionPostResponse)
async def upsert_vote(
    post_id: str,
    payload: DiscussionVoteRequest,
    request: Request,
    agent: Agent = Depends(require_agent_auth),
    db: Session = Depends(get_db),
) -> DiscussionPostResponse:
    body_hash = hash_body(await request.body())
    request_id = request.headers.get("X-Request-ID") or str(uuid4())
    post_ref = _find_post_by_identifier(db, post_id)
    if not post_ref:
        raise HTTPException(status_code=404, detail="Post not found")

    post = (
        db.query(
            DiscussionPost,
            DiscussionThread.thread_id,
            Agent.id.label("author_agent_num"),
            Agent.agent_id,
            Agent.name,
        )
        .join(DiscussionThread, DiscussionPost.thread_id == DiscussionThread.id)
        .join(Agent, DiscussionPost.author_agent_id == Agent.id)
        .filter(DiscussionPost.id == post_ref.id)
        .first()
    )
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")

    vote = (
        db.query(DiscussionVote)
        .filter(DiscussionVote.post_id == post.DiscussionPost.id, DiscussionVote.voter_agent_id == agent.id)
        .first()
    )
    if vote:
        vote.value = payload.value
    else:
        vote = DiscussionVote(post_id=post.DiscussionPost.id, voter_agent_id=agent.id, value=payload.value)
        db.add(vote)
    db.commit()

    record_audit(
        db,
        actor_type="agent",
        agent_id=agent.agent_id,
        method=request.method,
        path=request.url.path,
        idempotency_key=request.headers.get("Idempotency-Key"),
        body_hash=body_hash,
        signature_status="none",
        request_id=request_id,
    )

    return DiscussionPostResponse(
        success=True,
        data=DiscussionPostPublic(
            post_num=post.DiscussionPost.id,
            post_id=post.DiscussionPost.post_id,
            thread_id=post.thread_id,
            author_agent_num=int(post.author_agent_num),
            author_agent_id=post.agent_id,
            author_agent_name=post.name,
            body_md=post.DiscussionPost.body_md,
            created_at=post.DiscussionPost.created_at,
            score_sum=_post_score_sum(db, post.DiscussionPost.id),
            viewer_vote=None,
        ),
    )


@router.post("/api/v1/agent/discussions/posts/{post_id}/hide", response_model=DiscussionPostHideResponse)
async def hide_post(
    post_id: str,
    request: Request,
    agent: Agent = Depends(require_agent_auth),
    db: Session = Depends(get_db),
) -> DiscussionPostHideResponse:
    body_hash = hash_body(await request.body())
    request_id = request.headers.get("X-Request-ID") or str(uuid4())

    post_ref = _find_post_by_identifier(db, post_id)
    if not post_ref:
        raise HTTPException(status_code=404, detail="Post not found")
    post = db.query(DiscussionPost).filter(DiscussionPost.id == post_ref.id, DiscussionPost.hidden_at.is_(None)).first()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")
    if post.author_agent_id != agent.id:
        raise HTTPException(status_code=403, detail="Only the author can hide this post.")

    post.hidden_at = datetime.now(timezone.utc)
    post.hidden_by_agent_id = agent.id
    post.hidden_reason = "author_hidden"
    db.commit()

    record_audit(
        db,
        actor_type="agent",
        agent_id=agent.agent_id,
        method=request.method,
        path=request.url.path,
        idempotency_key=request.headers.get("Idempotency-Key"),
        body_hash=body_hash,
        signature_status="none",
        request_id=request_id,
    )

    return DiscussionPostHideResponse(
        success=True,
        data=DiscussionPostHideData(post_id=post.post_id, hidden_at=post.hidden_at),
    )


@router.post("/api/v1/agent/discussions/posts/{post_id}/flag", response_model=DiscussionPostFlagResponse)
async def flag_post(
    post_id: str,
    payload: DiscussionPostFlagRequest,
    request: Request,
    agent: Agent = Depends(require_agent_auth),
    db: Session = Depends(get_db),
) -> DiscussionPostFlagResponse:
    body_hash = hash_body(await request.body())
    request_id = request.headers.get("X-Request-ID") or str(uuid4())

    post_ref = _find_post_by_identifier(db, post_id)
    if not post_ref:
        raise HTTPException(status_code=404, detail="Post not found")
    post = db.query(DiscussionPost).filter(DiscussionPost.id == post_ref.id, DiscussionPost.hidden_at.is_(None)).first()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")

    flag = DiscussionPostFlag(
        post_id=post.id,
        flagger_agent_id=agent.id,
        reason=payload.reason.strip() if payload.reason else None,
    )
    _row, created = insert_or_get_by_unique(
        db,
        instance=flag,
        model=DiscussionPostFlag,
        unique_filter={"post_id": post.id, "flagger_agent_id": agent.id},
    )

    record_audit(
        db,
        actor_type="agent",
        agent_id=agent.agent_id,
        method=request.method,
        path=request.url.path,
        idempotency_key=request.headers.get("Idempotency-Key"),
        body_hash=body_hash,
        signature_status="none",
        request_id=request_id,
        commit=False,
    )
    db.commit()

    return DiscussionPostFlagResponse(
        success=True,
        data=DiscussionPostFlagData(post_id=post.post_id, flag_created=bool(created)),
    )


def _generate_thread_id(db: Session) -> str:
    for _ in range(5):
        candidate = f"dth_{secrets.token_hex(8)}"
        exists = db.query(DiscussionThread.id).filter(DiscussionThread.thread_id == candidate).first()
        if not exists:
            return candidate
    raise RuntimeError("Failed to generate unique thread id")


def _find_project_by_identifier(db: Session, identifier: str) -> Project | None:
    if identifier.isdigit():
        return db.query(Project).filter(Project.id == int(identifier)).first()
    return db.query(Project).filter(Project.project_id == identifier).first()


def _find_proposal_by_identifier(db: Session, identifier: str) -> Proposal | None:
    if identifier.isdigit():
        return db.query(Proposal).filter(Proposal.id == int(identifier)).first()
    return db.query(Proposal).filter(Proposal.proposal_id == identifier).first()


def _find_bounty_by_identifier(db: Session, identifier: str) -> Bounty | None:
    if identifier.isdigit():
        return db.query(Bounty).filter(Bounty.id == int(identifier)).first()
    return db.query(Bounty).filter(Bounty.bounty_id == identifier).first()


def _find_thread_by_identifier(db: Session, identifier: str) -> DiscussionThread | None:
    if identifier.isdigit():
        return db.query(DiscussionThread).filter(DiscussionThread.id == int(identifier)).first()
    return db.query(DiscussionThread).filter(DiscussionThread.thread_id == identifier).first()


def _generate_post_id(db: Session) -> str:
    for _ in range(5):
        candidate = f"dps_{secrets.token_hex(8)}"
        exists = db.query(DiscussionPost.id).filter(DiscussionPost.post_id == candidate).first()
        if not exists:
            return candidate
    raise RuntimeError("Failed to generate unique post id")


def _find_post_by_identifier(db: Session, identifier: str) -> DiscussionPost | None:
    if identifier.isdigit():
        return db.query(DiscussionPost).filter(DiscussionPost.id == int(identifier)).first()
    return db.query(DiscussionPost).filter(DiscussionPost.post_id == identifier).first()


def _post_score_sum(db: Session, post_pk: int) -> int:
    score = (
        db.query(func.coalesce(func.sum(DiscussionVote.value), 0))
        .filter(DiscussionVote.post_id == post_pk)
        .scalar()
    )
    return int(score or 0)
