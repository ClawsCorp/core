#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request


DEFAULT_CHAIN_ID_FALLBACK = 84532


def _json_rpc(url: str, method: str, params: list[object]) -> object:
    payload = json.dumps(
        {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    ).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            body = response.read()
    except urllib.error.URLError as exc:
        raise RuntimeError(f"{method} request failed: {exc}") from exc

    try:
        data = json.loads(body)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{method} returned invalid JSON.") from exc

    error = data.get("error")
    if error:
        message = error.get("message", "unknown error")
        code = error.get("code")
        raise RuntimeError(f"{method} returned RPC error {code}: {message}")

    if "result" not in data:
        raise RuntimeError(f"{method} response did not include result.")
    return data["result"]


def _parse_hex_int(value: object, label: str) -> int:
    if not isinstance(value, str) or not value.startswith("0x"):
        raise RuntimeError(f"{label} must be a hex string.")
    try:
        return int(value, 16)
    except ValueError as exc:
        raise RuntimeError(f"{label} was not a valid hex integer.") from exc


def _normalize_address(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    if not normalized.startswith("0x") or len(normalized) != 42:
        raise RuntimeError(f"Invalid address: {value}")
    return normalized.lower()


def main() -> int:
    env_default_chain_id_raw = os.getenv("DEFAULT_CHAIN_ID", "").strip()
    try:
        env_default_chain_id = (
            int(env_default_chain_id_raw) if env_default_chain_id_raw else DEFAULT_CHAIN_ID_FALLBACK
        )
    except ValueError:
        print(
            json.dumps(
                {
                    "success": False,
                    "error": "invalid_default_chain_id",
                    "hint": "DEFAULT_CHAIN_ID must be an integer.",
                }
            )
        )
        return 2

    parser = argparse.ArgumentParser(
        description="Smoke-check a candidate EVM RPC endpoint before cutover."
    )
    parser.add_argument(
        "--rpc-url",
        default=os.getenv("BASE_SEPOLIA_RPC_URL", "").strip(),
        help="RPC URL to test (defaults to BASE_SEPOLIA_RPC_URL).",
    )
    parser.add_argument(
        "--expected-chain-id",
        type=int,
        default=env_default_chain_id,
        help="Expected chain id (defaults to DEFAULT_CHAIN_ID, or 84532 if unset).",
    )
    parser.add_argument(
        "--usdc-address",
        default=os.getenv("USDC_ADDRESS", "").strip(),
        help="Optional contract to check via eth_getCode (defaults to USDC_ADDRESS).",
    )
    parser.add_argument(
        "--distributor-address",
        default=os.getenv("DIVIDEND_DISTRIBUTOR_CONTRACT_ADDRESS", "").strip(),
        help="Optional contract to check via eth_getCode (defaults to DIVIDEND_DISTRIBUTOR_CONTRACT_ADDRESS).",
    )
    args = parser.parse_args()

    rpc_url = (args.rpc_url or "").strip()
    if not rpc_url:
        print(
            json.dumps(
                {
                    "success": False,
                    "error": "missing_rpc_url",
                    "hint": "Set --rpc-url or BASE_SEPOLIA_RPC_URL.",
                }
            )
        )
        return 2

    try:
        usdc_address = _normalize_address(args.usdc_address)
        distributor_address = _normalize_address(args.distributor_address)

        chain_id_hex = _json_rpc(rpc_url, "eth_chainId", [])
        chain_id = _parse_hex_int(chain_id_hex, "eth_chainId")

        if chain_id != args.expected_chain_id:
            raise RuntimeError(
                f"Unexpected chain id: got {chain_id}, expected {args.expected_chain_id}."
            )

        block_number_hex = _json_rpc(rpc_url, "eth_blockNumber", [])
        block_number = _parse_hex_int(block_number_hex, "eth_blockNumber")

        contracts: dict[str, dict[str, object]] = {}
        for label, address in (
            ("usdc", usdc_address),
            ("dividend_distributor", distributor_address),
        ):
            if not address:
                continue
            code = _json_rpc(rpc_url, "eth_getCode", [address, "latest"])
            has_code = isinstance(code, str) and code not in {"0x", "0x0", ""}
            contracts[label] = {
                "address": address,
                "has_code": has_code,
            }
            if not has_code:
                raise RuntimeError(f"{label} contract returned empty code at {address}.")

        print(
            json.dumps(
                {
                    "success": True,
                    "rpc_url_present": True,
                    "chain_id": chain_id,
                    "latest_block": block_number,
                    "contracts": contracts,
                }
            )
        )
        return 0
    except RuntimeError as exc:
        print(
            json.dumps(
                {
                    "success": False,
                    "error": "rpc_smoke_failed",
                    "hint": str(exc),
                }
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
