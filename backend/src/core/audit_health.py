# SPDX-License-Identifier: BSL-1.1

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from threading import Lock


@dataclass(frozen=True)
class AuditInsertFailureEvent:
    observed_at: datetime
    actor_type: str
    path: str | None
    error_hint: str | None


_LOCK = Lock()
_FAILURES: deque[AuditInsertFailureEvent] = deque(maxlen=2048)


def note_audit_insert_failure(
    *,
    actor_type: str,
    path: str | None,
    error_hint: str | None,
    observed_at: datetime | None = None,
) -> None:
    now = observed_at or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    event = AuditInsertFailureEvent(
        observed_at=now,
        actor_type=str(actor_type or "unknown").strip()[:32] or "unknown",
        path=(str(path).strip()[:255] if path else None),
        error_hint=(str(error_hint).strip()[:255] if error_hint else None),
    )
    with _LOCK:
        _FAILURES.append(event)


def get_recent_audit_insert_failures(
    *,
    window_seconds: int,
    now: datetime | None = None,
) -> list[AuditInsertFailureEvent]:
    at = now or datetime.now(timezone.utc)
    if at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    threshold = at - timedelta(seconds=max(1, int(window_seconds)))
    with _LOCK:
        return [event for event in _FAILURES if event.observed_at >= threshold]


def reset_audit_insert_failures_for_tests() -> None:
    with _LOCK:
        _FAILURES.clear()
