#!/usr/bin/env python3
# SPDX-License-Identifier: BSL-1.1

"""Check Railway service visibility and recent deployment status.

Auth:
- Set env var RAILWAY_WORKSPACE_TOKEN (workspace/account token)

Example:
  RAILWAY_WORKSPACE_TOKEN=... python3 scripts/railway_health_check.py \
    --project-id cd76995a-d819-4b36-808b-422de3ff430e \
    --environment-name production \
    --service core --service usdc-indexer --service tx-worker --service autonomy-loop

The script is read-only and never prints the token.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from typing import Any
from urllib import error, request

API_URL = os.getenv("RAILWAY_API_URL", "").strip() or "https://api.railway.app/graphql/v2"


class RailwayApiError(RuntimeError):
    pass


def _json_dumps(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def _http_json(*, token: str, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
    body = _json_dumps({"query": query, "variables": variables or {}})
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
        "User-Agent": "ClawsCorp-core/railway-health-check",
    }
    req = request.Request(API_URL, data=body, headers=headers, method="POST")
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
        raise RailwayApiError(f"Railway API errors: {str(parsed.get('errors'))[:200]}")
    return parsed


@dataclass(frozen=True)
class ServiceStatus:
    name: str
    service_id: str
    found: bool
    deployment_status: str | None
    deployment_id: str | None
    deployment_created_at: str | None
    health: str


def _project_info(*, token: str, project_id: str) -> dict[str, Any]:
    q = """
query projectHealth($id: String!) {
  project(id: $id) {
    id
    name
    environments { edges { node { id name } } }
    services {
      edges {
        node {
          id
          name
          deployments(first: 1) {
            edges {
              node {
                id
                status
                createdAt
              }
            }
          }
        }
      }
    }
  }
}
""".strip()
    return _http_json(token=token, query=q, variables={"id": project_id})


def _normalize_status(value: Any) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    return s or None


def _assess_health(status: str | None) -> str:
    normalized = (status or "").upper()
    if normalized in {"SUCCESS", "SUCCESSFUL", "DEPLOYED", "HEALTHY", "ACTIVE"}:
        return "ok"
    if normalized in {"FAILED", "CRASHED", "ERROR", "REMOVED"}:
        return "critical"
    if normalized in {"BUILDING", "DEPLOYING", "INITIALIZING", "QUEUED", "PENDING", "IN_PROGRESS"}:
        return "warning"
    if normalized:
        return "unknown"
    return "warning"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project-id", default="cd76995a-d819-4b36-808b-422de3ff430e")
    ap.add_argument("--environment-name", default="production")
    ap.add_argument("--service", action="append", default=[], help="Service name to check (repeatable)")
    args = ap.parse_args()

    token = os.getenv("RAILWAY_WORKSPACE_TOKEN", "").strip()
    if not token:
        raise RailwayApiError("Missing env var RAILWAY_WORKSPACE_TOKEN")

    requested_services = [str(x).strip() for x in (args.service or []) if str(x).strip()]
    if not requested_services:
        requested_services = ["core", "usdc-indexer", "tx-worker", "autonomy-loop"]

    payload = _project_info(token=token, project_id=args.project_id)
    project = ((payload.get("data") or {}).get("project") or {})
    if not project:
        raise RailwayApiError("Project not found in API response")

    env_names = [
        str((((edge or {}).get("node") or {}).get("name") or "")).strip()
        for edge in (((project.get("environments") or {}).get("edges")) or [])
        if str((((edge or {}).get("node") or {}).get("name") or "")).strip()
    ]
    env_found = args.environment_name in env_names

    services_by_name: dict[str, dict[str, Any]] = {}
    for edge in (((project.get("services") or {}).get("edges")) or []):
        node = (edge or {}).get("node") or {}
        name = str(node.get("name") or "").strip()
        if name:
            services_by_name[name] = node

    results: list[ServiceStatus] = []
    overall_ok = bool(env_found)
    for name in requested_services:
        node = services_by_name.get(name)
        if not node:
            overall_ok = False
            results.append(
                ServiceStatus(
                    name=name,
                    service_id="",
                    found=False,
                    deployment_status=None,
                    deployment_id=None,
                    deployment_created_at=None,
                    health="critical",
                )
            )
            continue

        dep_edges = (((node.get("deployments") or {}).get("edges")) or [])
        dep = ((dep_edges[0] or {}).get("node") or {}) if dep_edges else {}
        status = _normalize_status(dep.get("status"))
        health = _assess_health(status)
        if health in {"critical", "warning", "unknown"}:
            overall_ok = False
        results.append(
            ServiceStatus(
                name=name,
                service_id=str(node.get("id") or ""),
                found=True,
                deployment_status=status,
                deployment_id=_normalize_status(dep.get("id")),
                deployment_created_at=_normalize_status(dep.get("createdAt")),
                health=health,
            )
        )

    out = {
        "success": overall_ok,
        "project_id": args.project_id,
        "environment_name": args.environment_name,
        "environment_found": env_found,
        "services": [
            {
                "name": row.name,
                "service_id": row.service_id,
                "found": row.found,
                "deployment_status": row.deployment_status,
                "deployment_id": row.deployment_id,
                "deployment_created_at": row.deployment_created_at,
                "health": row.health,
            }
            for row in results
        ],
    }
    sys.stdout.write(json.dumps(out, indent=2, ensure_ascii=True) + "\n")
    return 0 if overall_ok else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        sys.stderr.write(f"railway_health_check failed: {type(exc).__name__}: {str(exc)[:200]}\n")
        raise SystemExit(1)
