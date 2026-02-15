#!/usr/bin/env python3
# SPDX-License-Identifier: BSL-1.1

"""
Small helper to set Railway env vars via the Railway GraphQL Public API.

Auth:
- Set env var RAILWAY_WORKSPACE_TOKEN (workspace/account token)

Example:
  RAILWAY_WORKSPACE_TOKEN=... python3 scripts/railway_set_vars.py \\
    --project-id cd76995a-d819-4b36-808b-422de3ff430e \\
    --environment-name production \\
    --service-name core \\
    --set GOVENANCE_DISCUSSION_MINUTES=0 \\
    --set GOVENANCE_VOTING_MINUTES=2

Notes:
- Uses Authorization: Bearer <token> (workspace/account token).
- Never prints the token.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from typing import Any
from urllib import error, request


API_URL = "https://backboard.railway.com/graphql/v2"


class RailwayApiError(RuntimeError):
    pass


def _json_dumps(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def _http_json(*, token: str, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
    body = _json_dumps({"query": query, "variables": variables or {}})
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
        # Cloudflare blocks some default UAs; set one explicitly.
        "User-Agent": "ClawsCorp-core/railway-api-script",
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
class ProjectRef:
    id: str
    name: str


def _list_projects(*, token: str) -> list[ProjectRef]:
    q = "query { projects { edges { node { id name } } } }"
    data = _http_json(token=token, query=q).get("data") or {}
    edges = ((data.get("projects") or {}).get("edges")) or []
    out: list[ProjectRef] = []
    for e in edges:
        n = (e or {}).get("node") or {}
        pid = n.get("id")
        name = n.get("name")
        if isinstance(pid, str) and isinstance(name, str):
            out.append(ProjectRef(id=pid, name=name))
    return out


def _get_project_services_envs(*, token: str, project_id: str) -> dict[str, Any]:
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


def _variable_collection_upsert(
    *,
    token: str,
    project_id: str,
    environment_id: str,
    service_id: str,
    variables_map: dict[str, str],
    skip_deploys: bool,
) -> None:
    q = """
mutation variableCollectionUpsert($input: VariableCollectionUpsertInput!) {
  variableCollectionUpsert(input: $input)
}
""".strip()
    _http_json(
        token=token,
        query=q,
        variables={
            "input": {
                "projectId": project_id,
                "environmentId": environment_id,
                "serviceId": service_id,
                "variables": variables_map,
                "skipDeploys": bool(skip_deploys),
            }
        },
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project-id", required=False, default="cd76995a-d819-4b36-808b-422de3ff430e")
    ap.add_argument("--environment-name", default="production")
    ap.add_argument("--service-name", default="core")
    ap.add_argument("--skip-deploys", action="store_true")
    ap.add_argument("--set", action="append", default=[], help="KEY=VALUE (repeatable)")
    args = ap.parse_args()

    token = os.getenv("RAILWAY_WORKSPACE_TOKEN", "").strip()
    if not token:
        raise RailwayApiError("Missing env var RAILWAY_WORKSPACE_TOKEN")

    variables_map: dict[str, str] = {}
    for item in args.set:
        if "=" not in item:
            raise RailwayApiError(f"--set must be KEY=VALUE, got: {item}")
        k, v = item.split("=", 1)
        k = k.strip()
        v = v.strip()
        if not k:
            raise RailwayApiError("--set key must be non-empty")
        variables_map[k] = v
    if not variables_map:
        raise RailwayApiError("No variables provided; pass at least one --set KEY=VALUE")

    # Verify token can see the project list (sanity).
    projects = _list_projects(token=token)
    if not any(p.id == args.project_id for p in projects):
        names = ", ".join(sorted({p.name for p in projects})[:10])
        raise RailwayApiError(f"Project id not visible to token: {args.project_id}. Visible projects: {names}")

    info = _get_project_services_envs(token=token, project_id=args.project_id)
    proj = ((info.get("data") or {}).get("project") or {})
    if not proj:
        raise RailwayApiError("Project not found in API response")

    env_id: str | None = None
    for e in ((proj.get("environments") or {}).get("edges") or []):
        node = (e or {}).get("node") or {}
        if node.get("name") == args.environment_name:
            env_id = node.get("id")
            break
    if not isinstance(env_id, str):
        raise RailwayApiError(f"Environment not found: {args.environment_name}")

    service_id: str | None = None
    for e in ((proj.get("services") or {}).get("edges") or []):
        node = (e or {}).get("node") or {}
        if node.get("name") == args.service_name:
            service_id = node.get("id")
            break
    if not isinstance(service_id, str):
        raise RailwayApiError(f"Service not found: {args.service_name}")

    _variable_collection_upsert(
        token=token,
        project_id=args.project_id,
        environment_id=env_id,
        service_id=service_id,
        variables_map=variables_map,
        skip_deploys=bool(args.skip_deploys),
    )

    # Human output without leaking secrets.
    sys.stdout.write(
        json.dumps(
            {
                "success": True,
                "project_id": args.project_id,
                "environment": args.environment_name,
                "service": args.service_name,
                "keys_set": sorted(list(variables_map.keys())),
                "skip_deploys": bool(args.skip_deploys),
            },
            indent=2,
            ensure_ascii=True,
        )
        + "\n"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        sys.stderr.write(f"railway_set_vars failed: {type(exc).__name__}: {str(exc)[:200]}\n")
        raise SystemExit(1)

