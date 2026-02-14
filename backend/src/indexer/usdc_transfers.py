from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.core.config import get_settings
from src.core.database import SessionLocal
from src.models.indexer_cursor import IndexerCursor
from src.models.observed_usdc_transfer import ObservedUsdcTransfer
from src.models.project import Project

TRANSFER_TOPIC0 = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"


class IndexerError(Exception):
    pass


def _rpc_call(rpc_url: str, method: str, params: list[object]) -> object:
    payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode("utf-8")
    request = Request(rpc_url, data=payload, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urlopen(request, timeout=15) as response:
            body = response.read().decode("utf-8")
    except (HTTPError, URLError, TimeoutError) as exc:
        raise IndexerError(f"RPC request failed: method={method}") from exc

    try:
        parsed = json.loads(body)
    except json.JSONDecodeError as exc:
        raise IndexerError("RPC response is not valid JSON") from exc

    if parsed.get("error") is not None:
        raise IndexerError(f"RPC error: method={method}")

    return parsed.get("result")


def _looks_like_address(value: str | None) -> bool:
    if not value:
        return False
    v = value.strip().lower()
    if not v.startswith("0x"):
        return False
    if len(v) != 42:
        return False
    try:
        int(v[2:], 16)
    except ValueError:
        return False
    return True


def _topic_address(address: str) -> str:
    a = address.strip().lower()
    if not _looks_like_address(a):
        raise IndexerError("Invalid address")
    return "0x" + ("0" * 24) + a[2:]


def _hex_int(value: int) -> str:
    if value < 0:
        raise IndexerError("block number must be >= 0")
    return hex(value)


def _parse_hex_int(value: str) -> int:
    if not isinstance(value, str) or not value.startswith("0x"):
        raise IndexerError("expected 0x-prefixed hex string")
    try:
        return int(value, 16)
    except ValueError as exc:
        raise IndexerError("invalid hex int") from exc


def _parse_log_transfer(log: dict[str, object], *, chain_id: int, token_address: str) -> ObservedUsdcTransfer:
    topics = log.get("topics")
    data = log.get("data")
    block_number = log.get("blockNumber")
    tx_hash = log.get("transactionHash")
    log_index = log.get("logIndex")

    if not isinstance(topics, list) or len(topics) < 3:
        raise IndexerError("invalid log topics")
    if not isinstance(topics[0], str) or topics[0].lower() != TRANSFER_TOPIC0:
        raise IndexerError("not a Transfer log")
    if not isinstance(topics[1], str) or not isinstance(topics[2], str):
        raise IndexerError("invalid indexed topics")

    from_addr = "0x" + topics[1][-40:]
    to_addr = "0x" + topics[2][-40:]

    if not isinstance(data, str) or not data.startswith("0x"):
        raise IndexerError("invalid log data")
    try:
        amount = int(data, 16)
    except ValueError as exc:
        raise IndexerError("invalid transfer amount") from exc

    bn = _parse_hex_int(block_number) if isinstance(block_number, str) else None
    li = _parse_hex_int(log_index) if isinstance(log_index, str) else None
    if bn is None or li is None:
        raise IndexerError("missing blockNumber/logIndex")
    if not isinstance(tx_hash, str) or not tx_hash.startswith("0x") or len(tx_hash) != 66:
        raise IndexerError("invalid tx hash")

    return ObservedUsdcTransfer(
        chain_id=chain_id,
        token_address=token_address.lower(),
        from_address=from_addr.lower(),
        to_address=to_addr.lower(),
        amount_micro_usdc=amount,
        block_number=bn,
        tx_hash=tx_hash.lower(),
        log_index=li,
    )


def _get_or_create_cursor(db: Session, *, cursor_key: str, chain_id: int) -> IndexerCursor:
    row = (
        db.query(IndexerCursor)
        .filter(IndexerCursor.cursor_key == cursor_key, IndexerCursor.chain_id == chain_id)
        .first()
    )
    if row is not None:
        return row
    row = IndexerCursor(cursor_key=cursor_key, chain_id=chain_id, last_block_number=0)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _insert_transfer_idempotent(db: Session, row: ObservedUsdcTransfer) -> bool:
    db.add(row)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        return False
    return True


@dataclass(frozen=True)
class IndexRunResult:
    chain_id: int
    from_block: int
    to_block: int
    transfers_inserted: int
    transfers_seen: int
    cursor_key: str


def index_usdc_transfers(
    *,
    db: Session,
    rpc_url: str,
    usdc_address: str,
    cursor_key: str,
    from_block: int,
    to_block: int,
    watched_addresses: list[str],
) -> IndexRunResult:
    chain_hex = _rpc_call(rpc_url, "eth_chainId", [])
    chain_id = _parse_hex_int(chain_hex) if isinstance(chain_hex, str) else None
    if chain_id is None:
        raise IndexerError("unable to read chain id")

    if from_block > to_block:
        raise IndexerError("from_block must be <= to_block")

    watched_topics = [_topic_address(a) for a in watched_addresses if _looks_like_address(a)]
    if not watched_topics:
        return IndexRunResult(
            chain_id=chain_id,
            from_block=from_block,
            to_block=to_block,
            transfers_inserted=0,
            transfers_seen=0,
            cursor_key=cursor_key,
        )

    # Query logs where watched address is the sender, then where watched address is the recipient.
    logs_from = _rpc_call(
        rpc_url,
        "eth_getLogs",
        [
            {
                "fromBlock": _hex_int(from_block),
                "toBlock": _hex_int(to_block),
                "address": usdc_address,
                "topics": [TRANSFER_TOPIC0, watched_topics, None],
            }
        ],
    )
    logs_to = _rpc_call(
        rpc_url,
        "eth_getLogs",
        [
            {
                "fromBlock": _hex_int(from_block),
                "toBlock": _hex_int(to_block),
                "address": usdc_address,
                "topics": [TRANSFER_TOPIC0, None, watched_topics],
            }
        ],
    )

    seen: set[tuple[str, int]] = set()
    inserted = 0
    total_seen = 0

    for batch in (logs_from, logs_to):
        if not isinstance(batch, list):
            raise IndexerError("eth_getLogs result must be a list")
        for item in batch:
            if not isinstance(item, dict):
                continue
            try:
                row = _parse_log_transfer(item, chain_id=chain_id, token_address=usdc_address)
            except IndexerError:
                continue

            key = (row.tx_hash, int(row.log_index))
            if key in seen:
                continue
            seen.add(key)
            total_seen += 1
            if _insert_transfer_idempotent(db, row):
                inserted += 1

    # Update cursor to the highest block successfully scanned.
    cursor = _get_or_create_cursor(db, cursor_key=cursor_key, chain_id=chain_id)
    cursor.last_block_number = max(int(cursor.last_block_number or 0), int(to_block))
    cursor.updated_at = datetime.now(timezone.utc)
    db.add(cursor)
    db.commit()

    return IndexRunResult(
        chain_id=chain_id,
        from_block=from_block,
        to_block=to_block,
        transfers_inserted=inserted,
        transfers_seen=total_seen,
        cursor_key=cursor_key,
    )


def _resolve_watched_addresses(db: Session) -> list[str]:
    settings = get_settings()
    watched: list[str] = []
    if _looks_like_address(settings.dividend_distributor_contract_address or ""):
        watched.append(settings.dividend_distributor_contract_address.lower())
    if _looks_like_address(settings.funding_pool_contract_address or ""):
        watched.append(settings.funding_pool_contract_address.lower())
    for (addr,) in db.query(Project.treasury_address).filter(Project.treasury_address.isnot(None)).all():
        if _looks_like_address(addr):
            watched.append(str(addr).lower())
    for (addr,) in db.query(Project.revenue_address).filter(Project.revenue_address.isnot(None)).all():
        if _looks_like_address(addr):
            watched.append(str(addr).lower())
    # De-dupe while preserving order.
    out: list[str] = []
    seen: set[str] = set()
    for a in watched:
        if a in seen:
            continue
        seen.add(a)
        out.append(a)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="usdc-transfers-indexer")
    parser.add_argument("--cursor-key", default="usdc_transfers", help="DB cursor key")
    parser.add_argument("--from-block", type=int, default=None)
    parser.add_argument("--to-block", type=int, default=None)
    parser.add_argument("--lookback-blocks", type=int, default=500)
    parser.add_argument("--confirmations", type=int, default=5)
    args = parser.parse_args(argv)

    settings = get_settings()
    if not settings.database_url:
        raise SystemExit("DATABASE_URL is required for indexer")
    if not settings.base_sepolia_rpc_url:
        raise SystemExit("BASE_SEPOLIA_RPC_URL is required for indexer")
    if not settings.usdc_address or not _looks_like_address(settings.usdc_address):
        raise SystemExit("USDC_ADDRESS is required for indexer")

    if SessionLocal is None:
        raise SystemExit("DB SessionLocal is not configured")

    with SessionLocal() as db:
        watched = _resolve_watched_addresses(db)

        chain_hex = _rpc_call(settings.base_sepolia_rpc_url, "eth_chainId", [])
        chain_id = _parse_hex_int(chain_hex) if isinstance(chain_hex, str) else None
        if chain_id is None:
            raise SystemExit("Unable to read chain id")

        latest_hex = _rpc_call(settings.base_sepolia_rpc_url, "eth_blockNumber", [])
        latest = _parse_hex_int(latest_hex) if isinstance(latest_hex, str) else None
        if latest is None:
            raise SystemExit("Unable to read latest block")

        safe_tip = max(0, latest - int(args.confirmations))

        if args.to_block is not None:
            to_block = int(args.to_block)
        else:
            to_block = safe_tip

        if args.from_block is not None:
            from_block = int(args.from_block)
        else:
            cursor = _get_or_create_cursor(db, cursor_key=args.cursor_key, chain_id=chain_id)
            last = int(cursor.last_block_number or 0)
            from_block = max(0, last + 1)
            if from_block > to_block:
                from_block = max(0, to_block - int(args.lookback_blocks))

        result = index_usdc_transfers(
            db=db,
            rpc_url=settings.base_sepolia_rpc_url,
            usdc_address=settings.usdc_address.lower(),
            cursor_key=args.cursor_key,
            from_block=from_block,
            to_block=to_block,
            watched_addresses=watched,
        )

    print(
        json.dumps(
            {
                "success": True,
                "data": {
                    "chain_id": result.chain_id,
                    "from_block": result.from_block,
                    "to_block": result.to_block,
                    "cursor_key": result.cursor_key,
                    "transfers_seen": result.transfers_seen,
                    "transfers_inserted": result.transfers_inserted,
                },
            },
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
