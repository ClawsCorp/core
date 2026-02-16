#!/usr/bin/env python3
# SPDX-License-Identifier: BSL-1.1

"""Production preflight for ClawsCorp core.

Checks API health/stats/alerts and optional portal reachability.
Designed for CI/cron/operator use with machine-readable JSON output.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any
from urllib import error, request


DEFAULT_API_BASE = "https://core-production-b1a0.up.railway.app"
DEFAULT_PORTAL_BASE = "https://core-bice-mu.vercel.app"


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str
    data: dict[str, Any] | None = None


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _http_json(url: str, timeout_seconds: int) -> dict[str, Any]:
    req = request.Request(
        url,
        method="GET",
        headers={
            "Accept": "application/json",
            "User-Agent": "ClawsCorp-prod-preflight/1.0",
        },
    )
    try:
        with request.urlopen(req, timeout=timeout_seconds) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} for {url}: {body[:200]}") from exc
    except error.URLError as exc:
        raise RuntimeError(f"Network error for {url}: {exc.reason}") from exc

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Invalid JSON from {url}") from exc
    if not isinstance(parsed, dict):
        raise RuntimeError(f"Unexpected JSON shape from {url}")
    return parsed


def _http_status(url: str, timeout_seconds: int) -> int:
    req = request.Request(url, method="GET", headers={"User-Agent": "ClawsCorp-prod-preflight/1.0"})
    try:
        with request.urlopen(req, timeout=timeout_seconds) as resp:
            return int(resp.status)
    except error.HTTPError as exc:
        return int(exc.code)
    except error.URLError as exc:
        raise RuntimeError(f"Network error for {url}: {exc.reason}") from exc


def run_preflight(
    *,
    api_base_url: str,
    portal_base_url: str | None,
    timeout_seconds: int,
    fail_on_warning: bool,
    allowed_warning_types: set[str],
) -> tuple[bool, list[CheckResult], dict[str, Any]]:
    checks: list[CheckResult] = []
    meta: dict[str, Any] = {
        "api_base_url": api_base_url,
        "portal_base_url": portal_base_url,
        "timestamp": _utc_now_iso(),
    }

    # health
    health_url = f"{api_base_url.rstrip('/')}/api/v1/health"
    try:
        health = _http_json(health_url, timeout_seconds)
        ok = health.get("status") == "ok" and health.get("db") == "ok"
        checks.append(
            CheckResult(
                name="health",
                ok=bool(ok),
                detail="health and db must both be ok",
                data={"status": health.get("status"), "db": health.get("db"), "version": health.get("version")},
            )
        )
    except Exception as exc:
        checks.append(CheckResult(name="health", ok=False, detail=str(exc)))

    # stats
    stats_url = f"{api_base_url.rstrip('/')}/api/v1/stats"
    try:
        stats = _http_json(stats_url, timeout_seconds)
        data = stats.get("data") if isinstance(stats, dict) else None
        d = data if isinstance(data, dict) else {}
        cap_age = d.get("project_capital_reconciliation_max_age_seconds")
        rev_age = d.get("project_revenue_reconciliation_max_age_seconds")
        checks.append(
            CheckResult(
                name="stats",
                ok=True,
                detail="stats endpoint reachable",
                data={
                    "total_registered_agents": d.get("total_registered_agents"),
                    "project_capital_reconciliation_max_age_seconds": cap_age,
                    "project_revenue_reconciliation_max_age_seconds": rev_age,
                },
            )
        )
    except Exception as exc:
        checks.append(CheckResult(name="stats", ok=False, detail=str(exc)))

    # alerts
    alerts_url = f"{api_base_url.rstrip('/')}/api/v1/alerts"
    try:
        alerts = _http_json(alerts_url, timeout_seconds)
        items = (((alerts.get("data") or {}).get("items")) if isinstance(alerts, dict) else None) or []
        critical = [a for a in items if str((a or {}).get("severity", "")).lower() == "critical"]
        warning = [a for a in items if str((a or {}).get("severity", "")).lower() == "warning"]
        warning_not_allowed = [
            a
            for a in warning
            if str((a or {}).get("alert_type", "")) not in allowed_warning_types
        ]
        ok = len(critical) == 0 and (not fail_on_warning or len(warning_not_allowed) == 0)
        checks.append(
            CheckResult(
                name="alerts",
                ok=ok,
                detail=(
                    "no critical alerts" if not fail_on_warning else "no critical alerts and no disallowed warnings"
                ),
                data={
                    "critical_count": len(critical),
                    "warning_count": len(warning),
                    "warning_allowed_types": sorted(list(allowed_warning_types)),
                    "warning_disallowed_count": len(warning_not_allowed),
                    "critical_types": [str((a or {}).get("alert_type", "")) for a in critical],
                    "warning_disallowed_types": [str((a or {}).get("alert_type", "")) for a in warning_not_allowed],
                },
            )
        )
    except Exception as exc:
        checks.append(CheckResult(name="alerts", ok=False, detail=str(exc)))

    # portal reachability (optional)
    if portal_base_url:
        portal = portal_base_url.rstrip("/")
        try:
            root_status = _http_status(portal, timeout_seconds)
            apps_status = _http_status(f"{portal}/apps", timeout_seconds)
            ok = (200 <= root_status < 400) and (200 <= apps_status < 400)
            checks.append(
                CheckResult(
                    name="portal",
                    ok=ok,
                    detail="portal root and /apps must be reachable",
                    data={"root_status": root_status, "apps_status": apps_status},
                )
            )
        except Exception as exc:
            checks.append(CheckResult(name="portal", ok=False, detail=str(exc)))

    overall_ok = all(c.ok for c in checks)
    return overall_ok, checks, meta


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--api-base-url",
        default=os.getenv("ORACLE_BASE_URL", "").strip() or DEFAULT_API_BASE,
        help="Backend base URL",
    )
    parser.add_argument(
        "--portal-base-url",
        default=os.getenv("PORTAL_BASE_URL", "").strip() or DEFAULT_PORTAL_BASE,
        help="Frontend base URL (empty to skip portal check)",
    )
    parser.add_argument("--timeout-seconds", type=int, default=20)
    parser.add_argument("--fail-on-warning", action="store_true")
    parser.add_argument(
        "--allow-warning-type",
        action="append",
        default=[],
        help="Allowed warning alert_type (repeatable)",
    )
    args = parser.parse_args()

    api_base_url = args.api_base_url.rstrip("/")
    portal_base_url = args.portal_base_url.rstrip("/") if args.portal_base_url.strip() else None

    ok, checks, meta = run_preflight(
        api_base_url=api_base_url,
        portal_base_url=portal_base_url,
        timeout_seconds=max(3, int(args.timeout_seconds)),
        fail_on_warning=bool(args.fail_on_warning),
        allowed_warning_types={x.strip() for x in args.allow_warning_type if x and x.strip()},
    )

    out = {
        "success": ok,
        "meta": meta,
        "checks": [asdict(c) for c in checks],
    }
    sys.stdout.write(json.dumps(out, indent=2, ensure_ascii=True) + "\n")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
