from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from src.core.config import get_settings
from src.core.database import SessionLocal
from src.models.indexer_cursor import IndexerCursor
from src.oracle_runner.client import OracleClient, OracleRunnerError, load_config_from_env, to_json_bytes


@dataclass(frozen=True)
class TelegramObservedSignal:
    platform: str
    account_handle: str | None
    signal_url: str | None
    content_hash: str | None
    note: str | None
    idempotency_key: str


def _normalize_handle(value: str | None) -> str | None:
    text = str(value or "").strip().lower()
    if text.startswith("@"):
        text = text[1:]
    return text or None


def _normalize_text(value: str | None) -> str | None:
    text = " ".join(str(value or "").split())
    return text or None


def _content_hash(value: str | None) -> str | None:
    normalized = _normalize_text(value)
    if not normalized:
        return None
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _signal_url(username: str | None, message_id: int) -> str | None:
    handle = _normalize_handle(username)
    if not handle:
        return None
    return f"https://t.me/{handle}/{int(message_id)}"


def _cursor_key(channel_ref: str) -> str:
    normalized = _normalize_handle(channel_ref) or str(channel_ref).strip().lower()
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]
    return f"telegram_social:{digest}"


def _idempotency_key(channel_ref: str, message_id: int) -> str:
    normalized = _normalize_handle(channel_ref) or str(channel_ref).strip().lower()
    return f"obs:telegram:{normalized}:{int(message_id)}"


def _build_signal(channel_username: str | None, channel_ref: str, message_id: int, text: str | None) -> TelegramObservedSignal:
    return TelegramObservedSignal(
        platform="telegram",
        account_handle=_normalize_handle(channel_username),
        signal_url=_signal_url(channel_username, message_id),
        content_hash=_content_hash(text),
        note=f"telegram_channel:{_normalize_handle(channel_ref) or channel_ref};message_id:{int(message_id)}",
        idempotency_key=_idempotency_key(channel_ref, message_id),
    )


def _get_cursor(db: Session, channel_ref: str) -> int:
    key = _cursor_key(channel_ref)
    row = (
        db.query(IndexerCursor)
        .filter(IndexerCursor.cursor_key == key, IndexerCursor.chain_id == 0)
        .first()
    )
    if row is None:
        row = IndexerCursor(cursor_key=key, chain_id=0, last_block_number=0)
        db.add(row)
        db.commit()
        db.refresh(row)
    return int(row.last_block_number or 0)


def _advance_cursor(db: Session, channel_ref: str, last_message_id: int | None) -> None:
    if last_message_id is None:
        return
    key = _cursor_key(channel_ref)
    row = (
        db.query(IndexerCursor)
        .filter(IndexerCursor.cursor_key == key, IndexerCursor.chain_id == 0)
        .first()
    )
    if row is None:
        row = IndexerCursor(cursor_key=key, chain_id=0, last_block_number=int(last_message_id))
        db.add(row)
    else:
        row.last_block_number = int(last_message_id)
    db.commit()


async def _collect_channel(
    tg_client: Any,
    oracle_client: OracleClient,
    *,
    db: Session,
    channel_ref: str,
    batch_size: int,
) -> dict[str, int]:
    last_seen = _get_cursor(db, channel_ref)
    entity = await tg_client.get_entity(channel_ref)
    messages = await tg_client.get_messages(entity, limit=batch_size, min_id=last_seen)
    processed = 0
    inserted = 0
    max_message_id: int | None = None

    for message in reversed(list(messages)):
        message_id = int(getattr(message, "id", 0) or 0)
        if message_id <= 0:
            continue
        signal = _build_signal(getattr(entity, "username", None), channel_ref, message_id, getattr(message, "message", None))
        body = to_json_bytes(
            {
                "platform": signal.platform,
                "account_handle": signal.account_handle,
                "signal_url": signal.signal_url,
                "content_hash": signal.content_hash,
                "note": signal.note,
                "idempotency_key": signal.idempotency_key,
            }
        )
        oracle_client.post(
            "/api/v1/oracle/reputation/observed-social-signals",
            body_bytes=body,
            idempotency_key=signal.idempotency_key,
        )
        processed += 1
        inserted += 1
        max_message_id = message_id

    _advance_cursor(db, channel_ref, max_message_id)
    return {"processed": processed, "inserted": inserted, "last_message_id": max_message_id or last_seen}


async def _run_once() -> dict[str, Any]:
    settings = get_settings()
    if SessionLocal is None:
        raise OracleRunnerError("DATABASE_URL is required for telegram collector.")
    if settings.telegram_api_id is None:
        raise OracleRunnerError("TELEGRAM_API_ID is required.")
    if not settings.telegram_api_hash:
        raise OracleRunnerError("TELEGRAM_API_HASH is required.")
    if not settings.telegram_session_string:
        raise OracleRunnerError("TELEGRAM_SESSION_STRING is required.")
    if not settings.telegram_monitored_channels:
        raise OracleRunnerError("TELEGRAM_MONITORED_CHANNELS is required.")

    try:
        from telethon import TelegramClient
        from telethon.sessions import StringSession
    except ImportError as exc:
        raise OracleRunnerError("telethon is required for telegram collector.") from exc

    oracle_config = load_config_from_env()
    oracle_client = OracleClient(oracle_config)
    session = StringSession(settings.telegram_session_string)
    summary: dict[str, Any] = {"channels": []}

    async with TelegramClient(session, settings.telegram_api_id, settings.telegram_api_hash) as tg_client:
        db = SessionLocal()
        try:
            for channel_ref in settings.telegram_monitored_channels:
                channel_data = await _collect_channel(
                    tg_client,
                    oracle_client,
                    db=db,
                    channel_ref=channel_ref,
                    batch_size=int(settings.telegram_collector_batch_size),
                )
                channel_data["channel"] = channel_ref
                summary["channels"].append(channel_data)
        finally:
            db.close()
    summary["success"] = True
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="telegram-social-collector")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--sleep-seconds", type=int, default=0)
    args = parser.parse_args(argv)
    sleep_seconds = int(args.sleep_seconds or get_settings().telegram_collector_sleep_seconds)

    while True:
        try:
            result = asyncio.run(_run_once())
        except OracleRunnerError as exc:
            if args.json and not args.loop:
                print(json.dumps({"success": False, "error": str(exc)}, ensure_ascii=True))
            else:
                print(f"error={exc}")
            if not args.loop:
                return 1
        else:
            if args.json and not args.loop:
                print(json.dumps(result, ensure_ascii=True, sort_keys=True))
            else:
                for item in result.get("channels", []):
                    print(
                        "channel={channel} processed={processed} inserted={inserted} last_message_id={last_message_id}".format(
                            **item
                        )
                    )
            if not args.loop:
                return 0

        if sleep_seconds <= 0:
            sleep_seconds = 60
        import time

        time.sleep(sleep_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
