#!/usr/bin/env python3
# SPDX-License-Identifier: BSL-1.1

from __future__ import annotations

import argparse
import json
import os
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
CONTRACTS_DIR = REPO_ROOT / "contracts"


def _read_envfile(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and ((value[0] == value[-1] == '"') or (value[0] == value[-1] == "'")):
            value = value[1:-1]
        if key:
            values[key] = value
    return values


def _load_env(envfile: Path | None) -> dict[str, str]:
    merged: dict[str, str] = {}
    if envfile is not None:
        merged.update(_read_envfile(envfile))
    for key in (
        "BASE_SEPOLIA_RPC_URL",
        "DIVIDEND_DISTRIBUTOR_CONTRACT_ADDRESS",
        "SAFE_OWNER_ADDRESS",
        "SAFE_OWNER_KEYS_FILE",
        "CONTRACTS_DIR",
    ):
        value = os.getenv(key, "").strip()
        if value:
            merged[key] = value
    return merged


def _secure_mode(mode: int) -> bool:
    return (mode & (stat.S_IRWXG | stat.S_IRWXO)) == 0


def _inspect_keys_file(path: Path) -> dict[str, Any]:
    result: dict[str, Any] = {
        "path": str(path),
        "exists": path.exists(),
        "readable": False,
        "secure_permissions": False,
        "threshold": None,
        "owners_count": 0,
        "private_keys_count": 0,
        "errors": [],
    }
    if not path.exists():
        result["errors"].append("missing")
        return result

    try:
        st = path.stat()
        mode = stat.S_IMODE(st.st_mode)
        result["mode_octal"] = format(mode, "04o")
        result["secure_permissions"] = _secure_mode(mode)
        if not result["secure_permissions"]:
            result["errors"].append("permissions_too_open")
    except OSError:
        result["errors"].append("stat_failed")
        return result

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        result["readable"] = True
    except (OSError, ValueError):
        result["errors"].append("invalid_json")
        return result

    owners = payload.get("owners")
    if not isinstance(owners, list):
        result["errors"].append("owners_missing")
        return result

    threshold = payload.get("threshold")
    try:
        result["threshold"] = max(1, int(threshold or 2))
    except (TypeError, ValueError):
        result["errors"].append("invalid_threshold")
        return result

    result["owners_count"] = len(owners)
    keys_count = 0
    for item in owners:
        if not isinstance(item, dict):
            continue
        key = str(item.get("private_key") or "").strip()
        if key.startswith("0x") and len(key) >= 66:
            keys_count += 1
    result["private_keys_count"] = keys_count
    if keys_count < int(result["threshold"]):
        result["errors"].append("insufficient_keys_for_threshold")
    return result


def _owner_check(env: dict[str, str]) -> dict[str, Any]:
    contract_address = env.get("DIVIDEND_DISTRIBUTOR_CONTRACT_ADDRESS", "").strip()
    safe_owner = env.get("SAFE_OWNER_ADDRESS", "").strip()
    rpc_url = env.get("BASE_SEPOLIA_RPC_URL", "").strip()
    contracts_dir = Path(env.get("CONTRACTS_DIR", "").strip() or CONTRACTS_DIR).expanduser()

    result: dict[str, Any] = {
        "contract": contract_address,
        "expected_owner": safe_owner,
        "matches_expected_owner": False,
        "owner": None,
        "errors": [],
    }
    if not rpc_url:
        result["errors"].append("missing_rpc_url")
        return result
    if not contract_address:
        result["errors"].append("missing_contract_address")
        return result
    if not safe_owner:
        result["errors"].append("missing_safe_owner_address")
        return result

    cmd = [
        "npx",
        "hardhat",
        "run",
        "scripts/check-dividend-distributor-owner.js",
        "--network",
        "baseSepolia",
    ]
    run_env = os.environ.copy()
    run_env["BASE_SEPOLIA_RPC_URL"] = rpc_url
    run_env["DIVIDEND_DISTRIBUTOR_CONTRACT_ADDRESS"] = contract_address
    run_env["SAFE_OWNER_ADDRESS"] = safe_owner
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(contracts_dir),
            env=run_env,
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        result["errors"].append(f"owner_check_exec_failed:{type(exc).__name__}")
        return result

    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        result["errors"].append(f"owner_check_failed:{detail[:200] or proc.returncode}")
        return result

    lines = [line.strip() for line in (proc.stdout or "").splitlines() if line.strip()]
    parsed: dict[str, str] = {}
    for line in lines:
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        parsed[key.strip()] = value.strip()
    owner = parsed.get("owner")
    if owner:
        result["owner"] = owner
    result["matches_expected_owner"] = parsed.get("matches_expected_owner", "").lower() == "true"
    if not result["matches_expected_owner"]:
        result["errors"].append("owner_mismatch")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--envfile", default=str(Path.home() / ".oracle.env"))
    parser.add_argument("--allow-insecure-permissions", action="store_true")
    args = parser.parse_args()

    envfile = Path(args.envfile).expanduser() if args.envfile else None
    env = _load_env(envfile)
    blocked_reasons: list[str] = []

    keys_path_raw = env.get("SAFE_OWNER_KEYS_FILE", "").strip()
    if not keys_path_raw:
        blocked_reasons.append("missing_safe_owner_keys_file")
        keys_info: dict[str, Any] = {
            "path": None,
            "exists": False,
            "readable": False,
            "secure_permissions": False,
            "threshold": None,
            "owners_count": 0,
            "private_keys_count": 0,
            "errors": ["missing"],
        }
    else:
        keys_path = Path(keys_path_raw).expanduser()
        keys_info = _inspect_keys_file(keys_path)
        blocked_reasons.extend(str(item) for item in keys_info.get("errors") or [])
        if args.allow_insecure_permissions:
            blocked_reasons = [item for item in blocked_reasons if item != "permissions_too_open"]

    owner_info = _owner_check(env)
    blocked_reasons.extend(str(item) for item in owner_info.get("errors") or [])

    # Preserve order while removing duplicates.
    seen: set[str] = set()
    normalized_blocked: list[str] = []
    for item in blocked_reasons:
        if item not in seen:
            seen.add(item)
            normalized_blocked.append(item)

    payload = {
        "success": len(normalized_blocked) == 0,
        "envfile": str(envfile) if envfile is not None else None,
        "blocked_reasons": normalized_blocked,
        "keys_file": keys_info,
        "owner_check": owner_info,
    }
    print(json.dumps(payload, ensure_ascii=True, indent=2))
    return 0 if payload["success"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
