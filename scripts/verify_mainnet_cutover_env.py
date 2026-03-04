#!/usr/bin/env python3
# SPDX-License-Identifier: BSL-1.1

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib import error, request

from validate_mainnet_deploy_manifest import validate_manifest_payload


API_URL = os.getenv("RAILWAY_API_URL", "").strip() or "https://api.railway.app/graphql/v2"
DEFAULT_PROJECT_ID = "cd76995a-d819-4b36-808b-422de3ff430e"
DEFAULT_ENVIRONMENT_NAME = "production"
DEFAULT_SERVICES = ("core", "usdc-indexer", "tx-worker", "autonomy-loop")


class RailwayApiError(RuntimeError):
    pass


def _json_dumps(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def _http_json(*, token: str, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
    req = request.Request(
        API_URL,
        data=_json_dumps({"query": query, "variables": variables or {}}),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "ClawsCorp-core/mainnet-cutover-env-verify",
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


@dataclass(frozen=True)
class ServiceRef:
    id: str
    name: str


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


def _expected_env_for_service(manifest: dict[str, Any], service_name: str) -> dict[str, str]:
    contracts = manifest["contracts"]
    base = {
        "BLOCKCHAIN_RPC_URL": "__NON_EMPTY__",
    }
    if service_name == "core":
        return {
            **base,
            "DEFAULT_CHAIN_ID": str(int(manifest["network"]["chain_id"])),
            "USDC_ADDRESS": str(manifest["usdc_address"]),
            "DIVIDEND_DISTRIBUTOR_CONTRACT_ADDRESS": str(contracts["dividend_distributor"]["address"]),
            "FUNDING_POOL_CONTRACT_ADDRESS": str(contracts["funding_pool"]["address"]),
            "SAFE_OWNER_ADDRESS": str(manifest["safe"]["address"]),
        }
    if service_name == "usdc-indexer":
        return {
            **base,
            "USDC_ADDRESS": str(manifest["usdc_address"]),
        }
    if service_name == "tx-worker":
        return {
            **base,
            "USDC_ADDRESS": str(manifest["usdc_address"]),
            "DIVIDEND_DISTRIBUTOR_CONTRACT_ADDRESS": str(contracts["dividend_distributor"]["address"]),
            "SAFE_OWNER_ADDRESS": str(manifest["safe"]["address"]),
        }
    if service_name == "autonomy-loop":
        return {
            **base,
            "USDC_ADDRESS": str(manifest["usdc_address"]),
            "DIVIDEND_DISTRIBUTOR_CONTRACT_ADDRESS": str(contracts["dividend_distributor"]["address"]),
        }
    return base


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify that live Railway service env matches a validated mainnet deployment manifest."
    )
    parser.add_argument("manifest", help="Path to the validated deployment manifest JSON.")
    parser.add_argument("--project-id", default=DEFAULT_PROJECT_ID)
    parser.add_argument("--environment-name", default=DEFAULT_ENVIRONMENT_NAME)
    parser.add_argument("--service", action="append", default=[], help="Service name to verify (repeatable).")
    parser.add_argument(
        "--expected-rpc-url",
        default="",
        help="Optional exact RPC URL expected in BLOCKCHAIN_RPC_URL. If omitted, only non-empty presence is checked.",
    )
    args = parser.parse_args()

    token = os.getenv("RAILWAY_WORKSPACE_TOKEN", "").strip()
    if not token:
        print(json.dumps({"success": False, "error": "missing_railway_workspace_token"}))
        return 2

    try:
        manifest = _load_manifest(Path(args.manifest).expanduser())
        payload = _project_info(token=token, project_id=args.project_id)
        project = ((payload.get("data") or {}).get("project") or {})
        if not project:
            raise RailwayApiError("Project not found in API response")

        env_id = None
        for edge in (((project.get("environments") or {}).get("edges")) or []):
            node = (edge or {}).get("node") or {}
            if str(node.get("name") or "").strip() == args.environment_name:
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
        failures: list[dict[str, str]] = []
        service_results: list[dict[str, Any]] = []

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
                project_id=args.project_id,
                environment_id=env_id,
                service_id=ref.id,
            )
            expected = _expected_env_for_service(manifest, service_name)
            matches: list[dict[str, Any]] = []
            for key, expected_value in expected.items():
                current_value = str(current.get(key) or "")
                if key == "BLOCKCHAIN_RPC_URL":
                    if args.expected_rpc_url:
                        ok = current_value == args.expected_rpc_url
                        hint = "Expected exact RPC URL match."
                    else:
                        ok = bool(current_value.strip())
                        hint = "Expected a non-empty BLOCKCHAIN_RPC_URL."
                    if not ok and not current_value.strip():
                        legacy_value = str(current.get("BASE_SEPOLIA_RPC_URL") or "")
                        if legacy_value.strip():
                            failures.append(
                                {
                                    "service": service_name,
                                    "field": "BLOCKCHAIN_RPC_URL",
                                    "hint": "Missing preferred BLOCKCHAIN_RPC_URL; only legacy BASE_SEPOLIA_RPC_URL is set.",
                                }
                            )
                        else:
                            failures.append({"service": service_name, "field": "BLOCKCHAIN_RPC_URL", "hint": hint})
                    elif not ok:
                        failures.append({"service": service_name, "field": "BLOCKCHAIN_RPC_URL", "hint": hint})
                    matches.append({"key": key, "ok": ok, "present": bool(current_value.strip())})
                    continue

                ok = current_value == expected_value
                if not ok:
                    failures.append(
                        {
                            "service": service_name,
                            "field": key,
                            "hint": f"Expected {key} to match the deployment manifest.",
                        }
                    )
                matches.append({"key": key, "ok": ok})

            service_results.append(
                {
                    "service": service_name,
                    "service_id": ref.id,
                    "checks": matches,
                }
            )

        output = {
            "success": len(failures) == 0,
            "project_id": args.project_id,
            "environment_name": args.environment_name,
            "services": service_results,
            "failures": failures,
        }
        print(json.dumps(output, ensure_ascii=True))
        return 0 if output["success"] else 1
    except (RuntimeError, RailwayApiError) as exc:
        print(
            json.dumps(
                {
                    "success": False,
                    "error": "cutover_env_verification_failed",
                    "hint": str(exc),
                }
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
