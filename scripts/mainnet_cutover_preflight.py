#!/usr/bin/env python3
# SPDX-License-Identifier: BSL-1.1

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from validate_mainnet_deploy_manifest import validate_manifest_payload


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROJECT_ID = "cd76995a-d819-4b36-808b-422de3ff430e"
DEFAULT_ENVIRONMENT_NAME = "production"
DEFAULT_CHAIN_ID = 8453


def _read_manifest(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None, "manifest_not_found"
    except ValueError as exc:
        return None, f"invalid_json:{exc}"
    if not isinstance(payload, dict):
        return None, "invalid_manifest_type"
    errors = validate_manifest_payload(payload)
    if errors:
        return None, f"manifest_validation_failed:{json.dumps(errors, ensure_ascii=True)}"
    return payload, None


def _run_step(
    *,
    name: str,
    cmd: list[str],
    env: dict[str, str],
    timeout_seconds: int,
) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            cmd,
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {
            "step": name,
            "success": False,
            "error": "timeout",
            "command": cmd,
            "timeout_seconds": timeout_seconds,
        }

    stdout = (completed.stdout or "").strip()
    stderr = (completed.stderr or "").strip()
    parsed_stdout: Any = None
    if stdout:
        try:
            parsed_stdout = json.loads(stdout)
        except ValueError:
            parsed_stdout = stdout

    return {
        "step": name,
        "success": completed.returncode == 0,
        "exit_code": int(completed.returncode),
        "command": cmd,
        "stdout": parsed_stdout,
        "stderr": stderr or None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run a single fail-closed mainnet cutover preflight across manifest, RPC, on-chain, and Railway env checks."
    )
    parser.add_argument("manifest", help="Path to validated mainnet deployment manifest JSON.")
    parser.add_argument(
        "--rpc-url",
        default=(os.getenv("BLOCKCHAIN_RPC_URL", "").strip() or os.getenv("BASE_MAINNET_RPC_URL", "").strip()),
        help="Mainnet RPC URL (defaults to BLOCKCHAIN_RPC_URL then BASE_MAINNET_RPC_URL).",
    )
    parser.add_argument("--expected-chain-id", type=int, default=DEFAULT_CHAIN_ID)
    parser.add_argument("--project-id", default=DEFAULT_PROJECT_ID)
    parser.add_argument("--environment-name", default=DEFAULT_ENVIRONMENT_NAME)
    parser.add_argument("--service", action="append", default=[], help="Service name passed to verify_mainnet_cutover_env.py (repeatable).")
    parser.add_argument(
        "--railway-workspace-token",
        default="",
        help="Optional override for RAILWAY_WORKSPACE_TOKEN used by verify_mainnet_cutover_env.py.",
    )
    parser.add_argument(
        "--expected-rpc-url",
        default="",
        help="Optional exact RPC URL expected in Railway service env.",
    )
    parser.add_argument("--skip-rpc-smoke", action="store_true")
    parser.add_argument("--skip-onchain-verify", action="store_true")
    parser.add_argument("--skip-env-verify", action="store_true")
    parser.add_argument("--timeout-seconds", type=int, default=90)
    args = parser.parse_args()

    manifest_path = Path(args.manifest).expanduser()
    manifest, manifest_error = _read_manifest(manifest_path)
    if manifest is None:
        print(
            json.dumps(
                {
                    "success": False,
                    "error": "manifest_invalid",
                    "manifest": str(manifest_path),
                    "hint": manifest_error,
                }
            )
        )
        return 2

    rpc_url = str(args.rpc_url or "").strip()
    needs_rpc = (not args.skip_rpc_smoke) or (not args.skip_onchain_verify)
    if needs_rpc and not rpc_url:
        print(
            json.dumps(
                {
                    "success": False,
                    "error": "missing_rpc_url",
                    "hint": "Set --rpc-url or BLOCKCHAIN_RPC_URL / BASE_MAINNET_RPC_URL.",
                }
            )
        )
        return 2

    steps: list[dict[str, Any]] = []
    base_env = os.environ.copy()

    if not args.skip_rpc_smoke:
        rpc_step = _run_step(
            name="rpc_smoke",
            cmd=[
                sys.executable,
                str(REPO_ROOT / "scripts" / "rpc_endpoint_smoke.py"),
                "--rpc-url",
                rpc_url,
                "--expected-chain-id",
                str(int(args.expected_chain_id)),
                "--usdc-address",
                str(manifest["usdc_address"]),
                "--distributor-address",
                str(manifest["contracts"]["dividend_distributor"]["address"]),
            ],
            env=base_env,
            timeout_seconds=max(10, int(args.timeout_seconds)),
        )
        steps.append(rpc_step)
    else:
        steps.append({"step": "rpc_smoke", "success": True, "skipped": True})

    if not args.skip_onchain_verify:
        onchain_step = _run_step(
            name="onchain_manifest_verify",
            cmd=[
                sys.executable,
                str(REPO_ROOT / "scripts" / "verify_deploy_manifest_onchain.py"),
                str(manifest_path),
                "--rpc-url",
                rpc_url,
                "--expected-chain-id",
                str(int(args.expected_chain_id)),
            ],
            env=base_env,
            timeout_seconds=max(10, int(args.timeout_seconds)),
        )
        steps.append(onchain_step)
    else:
        steps.append({"step": "onchain_manifest_verify", "success": True, "skipped": True})

    if not args.skip_env_verify:
        env_verify_env = base_env.copy()
        override_token = str(args.railway_workspace_token or "").strip()
        if override_token:
            env_verify_env["RAILWAY_WORKSPACE_TOKEN"] = override_token
        env_cmd = [
            sys.executable,
            str(REPO_ROOT / "scripts" / "verify_mainnet_cutover_env.py"),
            str(manifest_path),
            "--project-id",
            str(args.project_id),
            "--environment-name",
            str(args.environment_name),
        ]
        if str(args.expected_rpc_url or "").strip():
            env_cmd.extend(["--expected-rpc-url", str(args.expected_rpc_url).strip()])
        for service_name in args.service:
            name = str(service_name or "").strip()
            if name:
                env_cmd.extend(["--service", name])
        env_step = _run_step(
            name="railway_env_verify",
            cmd=env_cmd,
            env=env_verify_env,
            timeout_seconds=max(10, int(args.timeout_seconds)),
        )
        steps.append(env_step)
    else:
        steps.append({"step": "railway_env_verify", "success": True, "skipped": True})

    failed_steps = [s["step"] for s in steps if not bool(s.get("success"))]
    result = {
        "success": len(failed_steps) == 0,
        "manifest": str(manifest_path),
        "expected_chain_id": int(args.expected_chain_id),
        "project_id": str(args.project_id),
        "environment_name": str(args.environment_name),
        "steps": steps,
        "failed_steps": failed_steps,
    }
    print(json.dumps(result, ensure_ascii=True))
    return 0 if result["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
