from __future__ import annotations

import json
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from src.core.config import get_settings

_BALANCE_OF_SELECTOR = "70a08231"


class BlockchainReadError(Exception):
    pass


class BlockchainConfigError(BlockchainReadError):
    pass


@dataclass(frozen=True)
class BalanceReadResult:
    balance_micro_usdc: int
    rpc_chain_id: int | None
    rpc_url_name: str


def read_usdc_balance_of_distributor() -> BalanceReadResult:
    settings = get_settings()
    rpc_url = settings.base_sepolia_rpc_url
    usdc_address = settings.usdc_address
    distributor_address = settings.dividend_distributor_contract_address
    if _is_invalid_rpc_config(rpc_url, usdc_address, distributor_address):
        raise BlockchainConfigError(
            "Missing BASE_SEPOLIA_RPC_URL, USDC_ADDRESS, or DIVIDEND_DISTRIBUTOR_CONTRACT_ADDRESS"
        )

    call_data = f"0x{_BALANCE_OF_SELECTOR}{_encode_address_arg(distributor_address)}"
    balance_hex = _rpc_call(
        rpc_url,
        "eth_call",
        [
            {
                "to": usdc_address,
                "data": call_data,
            },
            "latest",
        ],
    )
    if not isinstance(balance_hex, str) or not balance_hex.startswith("0x"):
        raise BlockchainReadError("Invalid eth_call response for balanceOf")

    try:
        balance = int(balance_hex, 16)
    except ValueError as exc:
        raise BlockchainReadError("Unable to parse eth_call balance response") from exc

    chain_id: int | None = None
    chain_hex = _rpc_call(rpc_url, "eth_chainId", [])
    if isinstance(chain_hex, str) and chain_hex.startswith("0x"):
        try:
            chain_id = int(chain_hex, 16)
        except ValueError:
            chain_id = None

    return BalanceReadResult(
        balance_micro_usdc=balance,
        rpc_chain_id=chain_id,
        rpc_url_name="base_sepolia",
    )


def _rpc_call(rpc_url: str, method: str, params: list[object]) -> object:
    payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode(
        "utf-8"
    )
    request = Request(rpc_url, data=payload, headers={"Content-Type": "application/json"}, method="POST")

    try:
        with urlopen(request, timeout=10) as response:
            body = response.read().decode("utf-8")
    except (HTTPError, URLError, TimeoutError) as exc:
        raise BlockchainReadError(f"RPC request failed for method={method}") from exc

    try:
        parsed = json.loads(body)
    except json.JSONDecodeError as exc:
        raise BlockchainReadError("RPC response is not valid JSON") from exc

    if parsed.get("error") is not None:
        raise BlockchainReadError(f"RPC error for method={method}")

    return parsed.get("result")


def _encode_address_arg(address: str) -> str:
    cleaned = address.lower()
    if not cleaned.startswith("0x"):
        raise BlockchainReadError("Address must be 0x-prefixed")
    raw = cleaned[2:]
    if len(raw) != 40:
        raise BlockchainReadError("Address must be 20 bytes")
    try:
        int(raw, 16)
    except ValueError as exc:
        raise BlockchainReadError("Address must be hex") from exc
    return raw.rjust(64, "0")


def _is_invalid_rpc_config(
    rpc_url: str | None, usdc_address: str | None, distributor_address: str | None
) -> bool:
    return any(
        value is None or _is_placeholder(value)
        for value in (rpc_url, usdc_address, distributor_address)
    )


def _is_placeholder(value: str) -> bool:
    normalized = value.strip().lower()
    if not normalized:
        return True
    if "<" in normalized or ">" in normalized:
        return True
    return "your" in normalized or "placeholder" in normalized
