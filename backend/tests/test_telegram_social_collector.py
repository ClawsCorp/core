from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from src.social import telegram_collector


def test_telegram_handle_and_signal_url_normalization() -> None:
    assert telegram_collector._normalize_handle("@ClawsChannel") == "clawschannel"
    assert telegram_collector._signal_url("ClawsChannel", 42) == "https://t.me/clawschannel/42"


def test_telegram_content_hash_and_idempotency_are_deterministic() -> None:
    assert telegram_collector._content_hash("Hello   world") == telegram_collector._content_hash("Hello world")
    assert telegram_collector._idempotency_key("@ClawsChannel", 42) == "obs:telegram:clawschannel:42"


def test_build_signal_uses_channel_username_for_handle_and_url() -> None:
    signal = telegram_collector._build_signal("ClawsChannel", "@ClawsChannel", 99, "Launch update")
    assert signal.platform == "telegram"
    assert signal.account_handle == "clawschannel"
    assert signal.signal_url == "https://t.me/clawschannel/99"
    assert signal.content_hash is not None
    assert signal.idempotency_key == "obs:telegram:clawschannel:99"
