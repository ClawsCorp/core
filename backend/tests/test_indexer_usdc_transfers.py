from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

# Make `src` importable whether pytest runs from repo root or backend/.
BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from src.core.database import Base
from src.indexer.usdc_transfers import _parse_log_transfer, _insert_transfer_idempotent

# Ensure tables are registered on Base.metadata
from src.models.indexer_cursor import IndexerCursor  # noqa: F401
from src.models.observed_usdc_transfer import ObservedUsdcTransfer  # noqa: F401


def test_parse_transfer_log() -> None:
    log = {
        "address": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
        "topics": [
            "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef",
            "0x0000000000000000000000001111111111111111111111111111111111111111",
            "0x0000000000000000000000002222222222222222222222222222222222222222",
        ],
        "data": "0x" + "0" * 62 + "2a",  # 42
        "blockNumber": "0x10",
        "transactionHash": "0x" + "3" * 64,
        "logIndex": "0x7",
    }
    row = _parse_log_transfer(log, chain_id=84532, token_address="0x" + "a" * 40)
    assert row.chain_id == 84532
    assert row.from_address == "0x1111111111111111111111111111111111111111"
    assert row.to_address == "0x2222222222222222222222222222222222222222"
    assert row.amount_micro_usdc == 42
    assert row.block_number == 16
    assert row.log_index == 7
    assert row.tx_hash == "0x" + "3" * 64


def test_insert_transfer_idempotent() -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)

    row = ObservedUsdcTransfer(
        chain_id=84532,
        token_address="0x" + "a" * 40,
        from_address="0x" + "1" * 40,
        to_address="0x" + "2" * 40,
        amount_micro_usdc=1,
        block_number=123,
        tx_hash="0x" + "3" * 64,
        log_index=0,
    )

    with session_local() as db:
        assert _insert_transfer_idempotent(db, row) is True
        db.commit()

    with session_local() as db:
        # Insert exact same unique key; should be treated as no-op.
        row2 = ObservedUsdcTransfer(
            chain_id=84532,
            token_address="0x" + "a" * 40,
            from_address="0x" + "1" * 40,
            to_address="0x" + "2" * 40,
            amount_micro_usdc=1,
            block_number=123,
            tx_hash="0x" + "3" * 64,
            log_index=0,
        )
        assert _insert_transfer_idempotent(db, row2) is False
        count = db.query(ObservedUsdcTransfer).count()
        assert count == 1

