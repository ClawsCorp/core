#!/usr/bin/env python3
# SPDX-License-Identifier: BSL-1.1

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from validate_mainnet_deploy_manifest import validate_manifest_payload


def _json_rpc(url: str, method: str, params: list[object]) -> object:
    payload = json.dumps(
        {"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
        separators=(",", ":"),
    ).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read()
    except urllib.error.URLError as exc:
        raise RuntimeError(f"{method} request failed: {exc}") from exc

    try:
        data = json.loads(raw)
    except ValueError as exc:
        raise RuntimeError(f"{method} returned invalid JSON") from exc

    if data.get("error"):
        err = data["error"]
        raise RuntimeError(f"{method} returned RPC error {err.get('code')}: {err.get('message', 'unknown error')}")
    if "result" not in data:
        raise RuntimeError(f"{method} response missing result")
    return data["result"]


def _parse_hex_int(value: object, label: str) -> int:
    if not isinstance(value, str) or not value.startswith("0x"):
        raise RuntimeError(f"{label} must be a hex string")
    try:
        return int(value, 16)
    except ValueError as exc:
        raise RuntimeError(f"{label} was not a valid hex integer") from exc


def _normalize_address(value: str) -> str:
    return value.lower()


def _load_manifest(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise RuntimeError("manifest_not_found")
    except ValueError as exc:
        raise RuntimeError(f"invalid_json: {exc}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("invalid_manifest_type")
    errors = validate_manifest_payload(payload)
    if errors:
        raise RuntimeError(f"manifest_validation_failed: {json.dumps(errors, ensure_ascii=True)}")
    return payload


def _check_receipt_ok(rpc_url: str, tx_hash: str, label: str) -> dict[str, object]:
    receipt = _json_rpc(rpc_url, "eth_getTransactionReceipt", [tx_hash])
    if receipt is None:
        raise RuntimeError(f"{label} receipt not found")
    if not isinstance(receipt, dict):
        raise RuntimeError(f"{label} receipt was not an object")
    status = _parse_hex_int(receipt.get("status"), f"{label}.status")
    block_number = _parse_hex_int(receipt.get("blockNumber"), f"{label}.blockNumber")
    if status != 1:
        raise RuntimeError(f"{label} receipt status={status}, expected 1")
    return {
        "tx_hash": tx_hash,
        "status": status,
        "block_number": block_number,
    }


def _check_code_present(rpc_url: str, address: str, label: str) -> dict[str, object]:
    code = _json_rpc(rpc_url, "eth_getCode", [address, "latest"])
    has_code = isinstance(code, str) and code not in {"0x", "0x0", ""}
    if not has_code:
        raise RuntimeError(f"{label} returned empty code")
    return {
        "address": address,
        "has_code": True,
    }


def _read_owner(rpc_url: str, distributor_address: str) -> str:
    result = _json_rpc(
        rpc_url,
        "eth_call",
        [
            {
                "to": distributor_address,
                "data": "0x8da5cb5b",
            },
            "latest",
        ],
    )
    if not isinstance(result, str) or not result.startswith("0x") or len(result) < 66:
        raise RuntimeError("owner() returned invalid result")
    return "0x" + result[-40:]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify that a validated deployment manifest matches real on-chain state."
    )
    parser.add_argument("manifest", help="Path to the validated deployment manifest JSON.")
    parser.add_argument(
        "--rpc-url",
        default=(
            os.getenv("BLOCKCHAIN_RPC_URL", "").strip()
            or os.getenv("BASE_MAINNET_RPC_URL", "").strip()
            or os.getenv("BASE_SEPOLIA_RPC_URL", "").strip()
        ),
        help="RPC URL to verify against (defaults to BLOCKCHAIN_RPC_URL, then BASE_MAINNET_RPC_URL, then BASE_SEPOLIA_RPC_URL).",
    )
    parser.add_argument(
        "--expected-chain-id",
        type=int,
        default=None,
        help="Optional override for expected chain id. Defaults to manifest.network.chain_id.",
    )
    args = parser.parse_args()

    manifest_path = Path(args.manifest).expanduser()
    rpc_url = (args.rpc_url or "").strip()
    if not rpc_url:
        print(
            json.dumps(
                {
                    "success": False,
                    "error": "missing_rpc_url",
                    "hint": "Set --rpc-url or BLOCKCHAIN_RPC_URL (or BASE_MAINNET_RPC_URL / BASE_SEPOLIA_RPC_URL).",
                }
            )
        )
        return 2

    try:
        manifest = _load_manifest(manifest_path)
        expected_chain_id = int(args.expected_chain_id or manifest["network"]["chain_id"])

        chain_id = _parse_hex_int(_json_rpc(rpc_url, "eth_chainId", []), "eth_chainId")
        if chain_id != expected_chain_id:
            raise RuntimeError(f"chain_id mismatch: got {chain_id}, expected {expected_chain_id}")

        contracts = manifest["contracts"]
        safe = manifest["safe"]
        ownership_transfer = manifest["ownership_transfer"]

        checks = {
            "usdc": _check_code_present(rpc_url, manifest["usdc_address"], "usdc"),
            "funding_pool": _check_code_present(rpc_url, contracts["funding_pool"]["address"], "funding_pool"),
            "dividend_distributor": _check_code_present(
                rpc_url,
                contracts["dividend_distributor"]["address"],
                "dividend_distributor",
            ),
            "safe": _check_code_present(rpc_url, safe["address"], "safe"),
            "funding_pool_deploy_receipt": _check_receipt_ok(
                rpc_url, contracts["funding_pool"]["deploy_tx_hash"], "funding_pool_deploy"
            ),
            "dividend_distributor_deploy_receipt": _check_receipt_ok(
                rpc_url, contracts["dividend_distributor"]["deploy_tx_hash"], "dividend_distributor_deploy"
            ),
            "safe_deploy_receipt": _check_receipt_ok(
                rpc_url, safe["deploy_tx_hash"], "safe_deploy"
            ),
            "ownership_transfer_receipt": _check_receipt_ok(
                rpc_url, ownership_transfer["tx_hash"], "ownership_transfer"
            ),
        }

        owner = _normalize_address(_read_owner(rpc_url, contracts["dividend_distributor"]["address"]))
        expected_owner = _normalize_address(safe["address"])
        if owner != expected_owner:
            raise RuntimeError(
                f"owner mismatch: distributor owner is {owner}, expected {expected_owner}"
            )

        print(
            json.dumps(
                {
                    "success": True,
                    "path": str(manifest_path),
                    "rpc_url_present": True,
                    "chain_id": chain_id,
                    "checks": checks,
                    "owner_check": {
                        "owner": owner,
                        "expected_owner": expected_owner,
                        "matches_expected_owner": True,
                    },
                }
            )
        )
        return 0
    except RuntimeError as exc:
        print(
            json.dumps(
                {
                    "success": False,
                    "path": str(manifest_path),
                    "error": "onchain_verification_failed",
                    "hint": str(exc),
                }
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
