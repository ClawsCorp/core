#!/usr/bin/env python3
# SPDX-License-Identifier: BSL-1.1

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from typing import Any
from urllib import error, request


API_URL = os.getenv("RAILWAY_API_URL", "").strip() or "https://api.railway.app/graphql/v2"
DEFAULT_PROJECT_ID = "cd76995a-d819-4b36-808b-422de3ff430e"
DEFAULT_ENVIRONMENT_NAME = "production"
DEFAULT_SERVICES = ("core", "usdc-indexer", "tx-worker", "autonomy-loop")


class RailwayApiError(RuntimeError):
    pass


@dataclass(frozen=True)
class ServiceRef:
    id: str
    name: str


def _json_dumps(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def _http_json(*, token: str, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
    req = request.Request(
        API_URL,
        data=_json_dumps({"query": query, "variables": variables or {}}),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "ClawsCorp-core/rpc-env-consistency-verify",
        },
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        raise RailwayApiError(f"HTTP {exc.code} from Railway API: {raw[:200]}") from exc
    except error.URLError as exc:
        raise RailwayApiError(f"Network error calling Railway API: {exc.reason}") from exc
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RailwayApiError("Railway API returned non-JSON response") from exc
    if not isinstance(parsed, dict):
        raise RailwayApiError("Railway API returned unexpected JSON shape")
    if parsed.get("errors"):
        raise RailwayApiError(f"Railway API errors: {str(parsed.get('errors'))[:300]}")
    return parsed


def _project_info(*, token: str, project_id: str) -> dict[str, Any]:
    q = """
query projectInfo($id: String!) {
  project(id: $id) {
    id
    name
    services { edges { node { id name } } }
    environments { edges { node { id name } } }
  }
}
""".strip()
    return _http_json(token=token, query=q, variables={"id": project_id})


def _fetch_service_variables(
    *,
    token: str,
    project_id: str,
    environment_id: str,
    service_id: str,
) -> dict[str, str]:
    q = """
query serviceVars($projectId: String!, $environmentId: String!, $serviceId: String!) {
  variables(projectId: $projectId, environmentId: $environmentId, serviceId: $serviceId)
}
""".strip()
    data = _http_json(
        token=token,
        query=q,
        variables={
            "projectId": project_id,
            "environmentId": environment_id,
            "serviceId": service_id,
        },
    )
    values: dict[str, str] = {}
    raw_variables = ((data.get("data") or {}).get("variables")) or {}
    if isinstance(raw_variables, dict):
        for key, value in raw_variables.items():
            name = str(key or "").strip()
            if name:
                values[name] = "" if value is None else str(value)
    return values


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify Railway services use consistent BLOCKCHAIN_RPC_URL values."
    )
    parser.add_argument("--project-id", default=DEFAULT_PROJECT_ID)
    parser.add_argument("--environment-name", default=DEFAULT_ENVIRONMENT_NAME)
    parser.add_argument("--service", action="append", default=[], help="Service name to verify (repeatable).")
    parser.add_argument(
        "--expected-rpc-url",
        default="",
        help="Optional exact value expected in BLOCKCHAIN_RPC_URL for all checked services.",
    )
    parser.add_argument(
        "--allow-legacy-fallback",
        action="store_true",
        help="Allow missing BLOCKCHAIN_RPC_URL when BASE_SEPOLIA_RPC_URL is set.",
    )
    args = parser.parse_args()

    token = os.getenv("RAILWAY_WORKSPACE_TOKEN", "").strip()
    if not token:
        print(json.dumps({"success": False, "error": "missing_railway_workspace_token"}))
        return 2

    try:
        payload = _project_info(token=token, project_id=str(args.project_id))
        project = ((payload.get("data") or {}).get("project") or {})
        if not project:
            raise RailwayApiError("Project not found in API response")

        env_id = None
        for edge in (((project.get("environments") or {}).get("edges")) or []):
            node = (edge or {}).get("node") or {}
            if str(node.get("name") or "").strip() == str(args.environment_name):
                env_id = str(node.get("id") or "").strip()
                break
        if not env_id:
            raise RailwayApiError(f"Environment not found: {args.environment_name}")

        services_by_name: dict[str, ServiceRef] = {}
        for edge in (((project.get("services") or {}).get("edges")) or []):
            node = (edge or {}).get("node") or {}
            name = str(node.get("name") or "").strip()
            sid = str(node.get("id") or "").strip()
            if name and sid:
                services_by_name[name] = ServiceRef(id=sid, name=name)

        requested = [str(x).strip() for x in (args.service or []) if str(x).strip()] or list(DEFAULT_SERVICES)
        expected_rpc = str(args.expected_rpc_url or "").strip()
        failures: list[dict[str, str]] = []
        service_results: list[dict[str, Any]] = []
        canonical_rpc: str | None = None

        for service_name in requested:
            ref = services_by_name.get(service_name)
            if ref is None:
                failures.append(
                    {
                        "service": service_name,
                        "field": "service",
                        "hint": "Service not found in Railway project.",
                    }
                )
                continue

            current = _fetch_service_variables(
                token=token,
                project_id=str(args.project_id),
                environment_id=env_id,
                service_id=ref.id,
            )
            preferred = str(current.get("BLOCKCHAIN_RPC_URL") or "").strip()
            legacy = str(current.get("BASE_SEPOLIA_RPC_URL") or "").strip()

            service_failures: list[dict[str, str]] = []
            preferred_present = bool(preferred)
            legacy_present = bool(legacy)
            resolved_value = preferred or legacy or ""
            resolved_from = "BLOCKCHAIN_RPC_URL" if preferred else ("BASE_SEPOLIA_RPC_URL" if legacy else "missing")

            if not preferred_present:
                if args.allow_legacy_fallback and legacy_present:
                    pass
                else:
                    service_failures.append(
                        {
                            "service": service_name,
                            "field": "BLOCKCHAIN_RPC_URL",
                            "hint": (
                                "Missing preferred BLOCKCHAIN_RPC_URL"
                                if legacy_present
                                else "Missing BLOCKCHAIN_RPC_URL and BASE_SEPOLIA_RPC_URL"
                            ),
                        }
                    )

            if expected_rpc:
                if preferred != expected_rpc:
                    service_failures.append(
                        {
                            "service": service_name,
                            "field": "BLOCKCHAIN_RPC_URL",
                            "hint": "BLOCKCHAIN_RPC_URL does not match expected value.",
                        }
                    )
            elif resolved_value:
                if canonical_rpc is None:
                    canonical_rpc = resolved_value
                elif resolved_value != canonical_rpc:
                    service_failures.append(
                        {
                            "service": service_name,
                            "field": "rpc_value",
                            "hint": "Resolved RPC URL differs across services.",
                        }
                    )

            failures.extend(service_failures)
            service_results.append(
                {
                    "service": service_name,
                    "service_id": ref.id,
                    "preferred_present": preferred_present,
                    "legacy_present": legacy_present,
                    "resolved_from": resolved_from,
                    "resolved_length": len(resolved_value),
                    "matches_expected": (preferred == expected_rpc) if expected_rpc else None,
                    "ok": len(service_failures) == 0,
                }
            )

        out = {
            "success": len(failures) == 0,
            "project_id": args.project_id,
            "environment_name": args.environment_name,
            "services": service_results,
            "canonical_rpc_length": len(canonical_rpc) if canonical_rpc else None,
            "expected_rpc_length": len(expected_rpc) if expected_rpc else None,
            "allow_legacy_fallback": bool(args.allow_legacy_fallback),
            "failures": failures,
        }
        print(json.dumps(out, ensure_ascii=True))
        return 0 if out["success"] else 1
    except (RuntimeError, RailwayApiError) as exc:
        print(json.dumps({"success": False, "error": "rpc_env_consistency_check_failed", "hint": str(exc)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
