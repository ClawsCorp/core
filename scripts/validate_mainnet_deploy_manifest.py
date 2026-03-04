#!/usr/bin/env python3
# SPDX-License-Identifier: BSL-1.1

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


EXPECTED_CHAIN_ID = 8453
EXPECTED_NETWORK_NAME = "base"
EXPECTED_RPC_ENV_VAR = "BLOCKCHAIN_RPC_URL"
_HEX_ADDRESS_RE = re.compile(r"^0x[a-fA-F0-9]{40}$")
_HEX_TX_RE = re.compile(r"^0x[a-fA-F0-9]{64}$")


def _require(condition: bool, field: str, hint: str, errors: list[dict[str, str]]) -> None:
    if not condition:
        errors.append({"field": field, "hint": hint})


def _is_address(value: object) -> bool:
    return isinstance(value, str) and _HEX_ADDRESS_RE.fullmatch(value) is not None


def _is_tx_hash(value: object) -> bool:
    return isinstance(value, str) and _HEX_TX_RE.fullmatch(value) is not None


def validate_manifest_payload(data: dict[str, Any]) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []

    _require(data.get("schema_version") == 1, "schema_version", "Expected schema_version=1.", errors)

    network = data.get("network")
    _require(isinstance(network, dict), "network", "network object is required.", errors)
    if isinstance(network, dict):
        _require(
            network.get("name") == EXPECTED_NETWORK_NAME,
            "network.name",
            f"Expected network.name={EXPECTED_NETWORK_NAME}.",
            errors,
        )
        _require(
            network.get("chain_id") == EXPECTED_CHAIN_ID,
            "network.chain_id",
            f"Expected network.chain_id={EXPECTED_CHAIN_ID}.",
            errors,
        )
        _require(
            network.get("rpc_env_var") == EXPECTED_RPC_ENV_VAR,
            "network.rpc_env_var",
            f"Expected network.rpc_env_var={EXPECTED_RPC_ENV_VAR}.",
            errors,
        )

    _require(
        isinstance(data.get("deployed_at"), str) and str(data.get("deployed_at")).endswith("Z"),
        "deployed_at",
        "Expected UTC ISO-8601 timestamp ending with Z.",
        errors,
    )

    deployer = data.get("deployer")
    _require(isinstance(deployer, dict), "deployer", "deployer object is required.", errors)
    if isinstance(deployer, dict):
        _require(
            _is_address(deployer.get("address")),
            "deployer.address",
            "Expected deployer.address to be a 20-byte hex address.",
            errors,
        )

    for field_name in ("usdc_address", "treasury_wallet_address", "founder_wallet_address"):
        _require(
            _is_address(data.get(field_name)),
            field_name,
            f"Expected {field_name} to be a 20-byte hex address.",
            errors,
        )

    contracts = data.get("contracts")
    _require(isinstance(contracts, dict), "contracts", "contracts object is required.", errors)
    if isinstance(contracts, dict):
        for contract_name in ("funding_pool", "dividend_distributor"):
            contract_payload = contracts.get(contract_name)
            _require(
                isinstance(contract_payload, dict),
                f"contracts.{contract_name}",
                f"{contract_name} object is required.",
                errors,
            )
            if isinstance(contract_payload, dict):
                _require(
                    _is_address(contract_payload.get("address")),
                    f"contracts.{contract_name}.address",
                    "Expected a 20-byte hex address.",
                    errors,
                )
                _require(
                    _is_tx_hash(contract_payload.get("deploy_tx_hash")),
                    f"contracts.{contract_name}.deploy_tx_hash",
                    "Expected a 32-byte tx hash.",
                    errors,
                )

    safe = data.get("safe")
    _require(isinstance(safe, dict), "safe", "safe object is required.", errors)
    safe_address = None
    if isinstance(safe, dict):
        safe_address = safe.get("address")
        _require(
            _is_address(safe_address),
            "safe.address",
            "Expected safe.address to be a 20-byte hex address.",
            errors,
        )
        _require(
            _is_tx_hash(safe.get("deploy_tx_hash")),
            "safe.deploy_tx_hash",
            "Expected a 32-byte tx hash.",
            errors,
        )
        owners = safe.get("owners")
        _require(isinstance(owners, list) and len(owners) >= 1, "safe.owners", "Expected at least one Safe owner.", errors)
        if isinstance(owners, list):
            for idx, owner in enumerate(owners):
                _require(
                    _is_address(owner),
                    f"safe.owners[{idx}]",
                    "Expected a 20-byte hex address.",
                    errors,
                )
        threshold = safe.get("threshold")
        _require(
            isinstance(threshold, int) and threshold >= 1,
            "safe.threshold",
            "Expected threshold >= 1.",
            errors,
        )
        if isinstance(threshold, int) and isinstance(owners, list):
            _require(
                threshold <= len(owners),
                "safe.threshold",
                "Threshold cannot exceed owners count.",
                errors,
            )

    ownership_transfer = data.get("ownership_transfer")
    _require(
        isinstance(ownership_transfer, dict),
        "ownership_transfer",
        "ownership_transfer object is required.",
        errors,
    )
    if isinstance(ownership_transfer, dict):
        _require(
            _is_tx_hash(ownership_transfer.get("tx_hash")),
            "ownership_transfer.tx_hash",
            "Expected a 32-byte tx hash.",
            errors,
        )
        new_owner = ownership_transfer.get("new_owner")
        _require(
            _is_address(new_owner),
            "ownership_transfer.new_owner",
            "Expected a 20-byte hex address.",
            errors,
        )
        if _is_address(new_owner) and _is_address(safe_address):
            _require(
                str(new_owner).lower() == str(safe_address).lower(),
                "ownership_transfer.new_owner",
                "ownership_transfer.new_owner must match safe.address.",
                errors,
            )

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate a Base mainnet deployment manifest before using it as the cutover source of truth."
    )
    parser.add_argument(
        "manifest",
        help="Path to the deployment manifest JSON file.",
    )
    args = parser.parse_args()

    manifest_path = Path(args.manifest).expanduser()
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        print(json.dumps({"success": False, "error": "manifest_not_found", "path": str(manifest_path)}))
        return 2
    except ValueError as exc:
        print(
            json.dumps(
                {
                    "success": False,
                    "error": "invalid_json",
                    "path": str(manifest_path),
                    "hint": str(exc),
                }
            )
        )
        return 2

    if not isinstance(payload, dict):
        print(
            json.dumps(
                {
                    "success": False,
                    "error": "invalid_manifest_type",
                    "path": str(manifest_path),
                    "hint": "Top-level JSON value must be an object.",
                }
            )
        )
        return 2

    errors = validate_manifest_payload(payload)
    if errors:
        print(
            json.dumps(
                {
                    "success": False,
                    "error": "manifest_validation_failed",
                    "path": str(manifest_path),
                    "errors": errors,
                }
            )
        )
        return 1

    print(
        json.dumps(
            {
                "success": True,
                "path": str(manifest_path),
                "chain_id": EXPECTED_CHAIN_ID,
                "safe_address": payload["safe"]["address"],
                "dividend_distributor_address": payload["contracts"]["dividend_distributor"]["address"],
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
