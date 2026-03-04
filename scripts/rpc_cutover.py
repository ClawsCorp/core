#!/usr/bin/env python3
# SPDX-License-Identifier: BSL-1.1

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


DEFAULT_PROJECT_ID = "cd76995a-d819-4b36-808b-422de3ff430e"
DEFAULT_ENVIRONMENT_NAME = "production"
DEFAULT_API_BASE_URL = "https://core-production-b1a0.up.railway.app"
TARGET_SERVICES = ("core", "usdc-indexer", "tx-worker", "autonomy-loop")


def _run(
    cmd: list[str],
    *,
    cwd: Path,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        cmd,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


def _tail_lines(value: str, limit: int = 12) -> list[str]:
    lines = [line for line in (value or "").splitlines() if line.strip()]
    return lines[-limit:]


def _completed_payload(
    completed: subprocess.CompletedProcess[str],
    *,
    ok: bool | None = None,
) -> dict[str, object]:
    success = completed.returncode == 0 if ok is None else bool(ok)
    return {
        "ok": success,
        "return_code": completed.returncode,
        "stdout_tail": _tail_lines(completed.stdout),
        "stderr_tail": _tail_lines(completed.stderr),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Semi-automated pre-release RPC cutover orchestration for Railway."
    )
    parser.add_argument(
        "--new-rpc-url",
        required=True,
        help="Candidate Base Sepolia RPC URL to validate and publish.",
    )
    parser.add_argument(
        "--project-id",
        default=DEFAULT_PROJECT_ID,
        help=f"Railway project id (default: {DEFAULT_PROJECT_ID}).",
    )
    parser.add_argument(
        "--environment-name",
        default=DEFAULT_ENVIRONMENT_NAME,
        help=f"Railway environment name (default: {DEFAULT_ENVIRONMENT_NAME}).",
    )
    parser.add_argument(
        "--api-base-url",
        default=DEFAULT_API_BASE_URL,
        help=f"Backend API base URL (default: {DEFAULT_API_BASE_URL}).",
    )
    parser.add_argument(
        "--ops-smoke-env-file",
        default="/Users/alex/.oracle.env",
        help="Env file for prod_preflight ops smoke.",
    )
    parser.add_argument(
        "--ops-smoke-month",
        default="auto",
        help="Month passed through to prod_preflight ops smoke.",
    )
    parser.add_argument(
        "--ops-smoke-tx-max-tasks",
        type=int,
        default=5,
        help="tx task limit passed through to prod_preflight ops smoke.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually write BASE_SEPOLIA_RPC_URL to Railway. Without this flag, run as dry-run only.",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    smoke_script = repo_root / "scripts" / "rpc_endpoint_smoke.py"
    set_vars_script = repo_root / "scripts" / "railway_set_vars.py"
    health_script = repo_root / "scripts" / "railway_health_check.py"
    preflight_script = repo_root / "scripts" / "prod_preflight.py"

    result: dict[str, object] = {
        "success": False,
        "mode": "apply" if args.apply else "dry_run",
        "project_id": args.project_id,
        "environment_name": args.environment_name,
        "api_base_url": args.api_base_url.rstrip("/"),
        "services": list(TARGET_SERVICES),
        "steps": {},
    }
    steps: dict[str, object] = result["steps"]  # type: ignore[assignment]

    smoke = _run(
        [sys.executable, str(smoke_script), "--rpc-url", args.new_rpc_url],
        cwd=repo_root,
    )
    steps["candidate_rpc_smoke"] = _completed_payload(smoke)
    if smoke.returncode != 0:
        print(json.dumps(result))
        return 1

    if not args.apply:
        result["hint"] = "Re-run with --apply to update Railway. Candidate RPC validation is still executed."
        result["success"] = True
        print(json.dumps(result))
        return 0

    token = os.getenv("RAILWAY_WORKSPACE_TOKEN", "").strip()
    if not token:
        result["steps"] = steps
        steps["railway_auth"] = {
            "ok": False,
            "error": "missing_railway_workspace_token",
        }
        print(json.dumps(result))
        return 2

    for service_name in TARGET_SERVICES:
        completed = _run(
            [
                sys.executable,
                str(set_vars_script),
                "--project-id",
                args.project_id,
                "--environment-name",
                args.environment_name,
                "--service-name",
                service_name,
                "--set",
                f"BASE_SEPOLIA_RPC_URL={args.new_rpc_url}",
            ],
            cwd=repo_root,
            extra_env={"RAILWAY_WORKSPACE_TOKEN": token},
        )
        steps[f"set_{service_name}"] = _completed_payload(completed)
        if completed.returncode != 0:
            print(json.dumps(result))
            return 1

    health = _run(
        [
            sys.executable,
            str(health_script),
            "--project-id",
            args.project_id,
            "--environment-name",
            args.environment_name,
        ],
        cwd=repo_root,
        extra_env={"RAILWAY_WORKSPACE_TOKEN": token},
    )
    steps["railway_health"] = _completed_payload(health)
    if health.returncode != 0:
        print(json.dumps(result))
        return 1

    preflight = _run(
        [
            sys.executable,
            str(preflight_script),
            "--api-base-url",
            args.api_base_url.rstrip("/"),
            "--run-ops-smoke",
            "--ops-smoke-env-file",
            args.ops_smoke_env_file,
            "--ops-smoke-month",
            args.ops_smoke_month,
            "--ops-smoke-tx-max-tasks",
            str(max(1, int(args.ops_smoke_tx_max_tasks))),
            "--fail-on-warning",
        ],
        cwd=repo_root,
    )
    steps["prod_preflight"] = _completed_payload(preflight)
    if preflight.returncode != 0:
        print(json.dumps(result))
        return 1

    result["success"] = True
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
