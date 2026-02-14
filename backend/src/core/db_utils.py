# SPDX-License-Identifier: BSL-1.1

from __future__ import annotations

from typing import Any, TypeVar

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

ModelT = TypeVar("ModelT")


def insert_or_get_by_unique(
    db: Session,
    *,
    instance: ModelT,
    model: type[ModelT],
    unique_filter: dict[str, Any],
) -> tuple[ModelT, bool]:
    """Insert an instance with race-safe fallback to the existing row.

    Returns ``(row, created)`` where ``created`` is False when a uniqueness race
    occurred and the existing row matching ``unique_filter`` was loaded.
    """

    if db.in_transaction():
        nested = db.begin_nested()
        try:
            db.add(instance)
            db.flush()
            nested.commit()
            return instance, True
        except IntegrityError as exc:
            nested.rollback()
            integrity_error = exc
    else:
        try:
            db.add(instance)
            db.flush()
            return instance, True
        except IntegrityError as exc:
            db.rollback()
            integrity_error = exc

    existing = db.query(model).filter_by(**unique_filter).first()
    if existing is None:
        raise integrity_error
    return existing, False
