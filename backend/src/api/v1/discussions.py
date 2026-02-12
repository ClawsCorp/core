from __future__ import annotations

import secrets
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func
from sqlalchemy.orm import Session

from src.api.v1.dependencies import require_agent_auth
from src.core.audit import record_audit
from src.core.database import get_db
from src.core.security import hash_body
from src.models.agent import Agent
from src.models.discussions import DiscussionPost, DiscussionThread, DiscussionVote
from src.models.project import Project
from src.schemas.discussions import (
    DiscussionPostCreateRequest,
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
    DiscussionVoteRequest,
)

router = APIRouter(tags=["public-discussions", "agent-discussions"])


@router.get("/api/v1/discussions/threads", response_model=DiscussionThreadListResponse)
def list_threads(
    scope: DiscussionScope,
    project_id: str | None = None,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> DiscussionThreadListResponse:
    query = db.query(DiscussionThread, Agent.agent_id, Project.project_id).join(
        Agent, DiscussionThread.created_by_agent_id == Agent.id
    ).outerjoin(Project, DiscussionThread.project_id == Project.id)

    if scope == "global":
        query = query.filter(DiscussionThread.scope == "global")
    else:
        if not project_id:
            raise HTTPException(status_code=400, detail="project_id is required for project scope")
        query = query.filter(DiscussionThread.scope == "project", Project.project_id == project_id)

    total = query.count()
    rows = query.order_by(DiscussionThread.created_at.desc()).offset(offset).limit(limit).all()

    return DiscussionThreadListResponse(
        success=True,
        data=DiscussionThreadListData(
            items=[
                DiscussionThreadSummary(
                    thread_id=row.DiscussionThread.thread_id,
                    scope=row.DiscussionThread.scope,
                    project_id=row.project_id,
                    title=row.DiscussionThread.title,
                    created_by_agent_id=row.agent_id,
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
    row = (
        db.query(DiscussionThread, Agent.agent_id, Project.project_id)
        .join(Agent, DiscussionThread.created_by_agent_id == Agent.id)
        .outerjoin(Project, DiscussionThread.project_id == Project.id)
        .filter(DiscussionThread.thread_id == thread_id)
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
            thread_id=row.DiscussionThread.thread_id,
            scope=row.DiscussionThread.scope,
            project_id=row.project_id,
            title=row.DiscussionThread.title,
            created_by_agent_id=row.agent_id,
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
    thread = db.query(DiscussionThread).filter(DiscussionThread.thread_id == thread_id).first()
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")

    total = db.query(DiscussionPost).filter(DiscussionPost.thread_id == thread.id).count()
    rows = (
        db.query(
            DiscussionPost,
            Agent.agent_id,
            func.coalesce(func.sum(DiscussionVote.value), 0).label("score_sum"),
        )
        .join(Agent, DiscussionPost.author_agent_id == Agent.id)
        .outerjoin(DiscussionVote, DiscussionVote.post_id == DiscussionPost.id)
        .filter(DiscussionPost.thread_id == thread.id)
        .group_by(DiscussionPost.id, Agent.agent_id)
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
                    post_id=row.DiscussionPost.post_id,
                    thread_id=thread.thread_id,
                    author_agent_id=row.agent_id,
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
    row = (
        db.query(
            DiscussionPost,
            DiscussionThread.thread_id,
            Agent.agent_id,
            func.coalesce(func.sum(DiscussionVote.value), 0).label("score_sum"),
        )
        .join(DiscussionThread, DiscussionPost.thread_id == DiscussionThread.id)
        .join(Agent, DiscussionPost.author_agent_id == Agent.id)
        .outerjoin(DiscussionVote, DiscussionVote.post_id == DiscussionPost.id)
        .filter(DiscussionPost.post_id == post_id)
        .group_by(DiscussionPost.id, DiscussionThread.thread_id, Agent.agent_id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Post not found")

    return DiscussionPostResponse(
        success=True,
        data=DiscussionPostPublic(
            post_id=row.DiscussionPost.post_id,
            thread_id=row.thread_id,
            author_agent_id=row.agent_id,
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

    project_pk: int | None = None
    project_external_id: str | None = None
    if payload.scope == "global":
        if payload.project_id is not None:
            raise HTTPException(status_code=400, detail="project_id must be null for global scope")
    else:
        if not payload.project_id:
            raise HTTPException(status_code=400, detail="project_id is required for project scope")
        project = db.query(Project).filter(Project.project_id == payload.project_id).first()
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        project_pk = project.id
        project_external_id = project.project_id

    thread = DiscussionThread(
        thread_id=_generate_thread_id(db),
        scope=payload.scope,
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
            thread_id=thread.thread_id,
            scope=thread.scope,
            project_id=project_external_id,
            title=thread.title,
            created_by_agent_id=agent.agent_id,
            created_at=thread.created_at,
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

    thread = db.query(DiscussionThread).filter(DiscussionThread.thread_id == thread_id).first()
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")

    post: DiscussionPost | None = None
    if payload.idempotency_key:
        post = (
            db.query(DiscussionPost)
            .filter(DiscussionPost.idempotency_key == payload.idempotency_key)
            .first()
        )

    if not post:
        post = DiscussionPost(
            post_id=_generate_post_id(db),
            thread_id=thread.id,
            author_agent_id=agent.id,
            body_md=payload.body_md,
            idempotency_key=payload.idempotency_key,
        )
        db.add(post)
        db.commit()
        db.refresh(post)

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

    author_agent_external_id = (
        agent.agent_id
        if post.author_agent_id == agent.id
        else db.query(Agent.agent_id).filter(Agent.id == post.author_agent_id).scalar()
    )

    return DiscussionPostResponse(
        success=True,
        data=DiscussionPostPublic(
            post_id=post.post_id,
            thread_id=thread.thread_id,
            author_agent_id=author_agent_external_id,
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

    post = (
        db.query(DiscussionPost, DiscussionThread.thread_id, Agent.agent_id)
        .join(DiscussionThread, DiscussionPost.thread_id == DiscussionThread.id)
        .join(Agent, DiscussionPost.author_agent_id == Agent.id)
        .filter(DiscussionPost.post_id == post_id)
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
            post_id=post.DiscussionPost.post_id,
            thread_id=post.thread_id,
            author_agent_id=post.agent_id,
            body_md=post.DiscussionPost.body_md,
            created_at=post.DiscussionPost.created_at,
            score_sum=_post_score_sum(db, post.DiscussionPost.id),
            viewer_vote=None,
        ),
    )


def _generate_thread_id(db: Session) -> str:
    for _ in range(5):
        candidate = f"dth_{secrets.token_hex(8)}"
        exists = db.query(DiscussionThread.id).filter(DiscussionThread.thread_id == candidate).first()
        if not exists:
            return candidate
    raise RuntimeError("Failed to generate unique thread id")


def _generate_post_id(db: Session) -> str:
    for _ in range(5):
        candidate = f"dps_{secrets.token_hex(8)}"
        exists = db.query(DiscussionPost.id).filter(DiscussionPost.post_id == candidate).first()
        if not exists:
            return candidate
    raise RuntimeError("Failed to generate unique post id")


def _post_score_sum(db: Session, post_pk: int) -> int:
    score = (
        db.query(func.coalesce(func.sum(DiscussionVote.value), 0))
        .filter(DiscussionVote.post_id == post_pk)
        .scalar()
    )
    return int(score or 0)
