#!/usr/bin/env python3
# SPDX-License-Identifier: BSL-1.1

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _read_json(path: str | None) -> dict[str, Any] | None:
    if not path:
        return None
    payload = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path}: top-level JSON must be an object")
    return payload


def _extract_check(preflight: dict[str, Any] | None, name: str) -> dict[str, Any] | None:
    if not preflight:
        return None
    checks = preflight.get("checks")
    if not isinstance(checks, list):
        return None
    for row in checks:
        if isinstance(row, dict) and str(row.get("name") or "") == name:
            return row
    return None


def _fmt_bool(value: bool | None) -> str:
    if value is True:
        return "yes"
    if value is False:
        return "no"
    return "unknown"


def _markdown_escape(value: str) -> str:
    return value.replace("|", "\\|")


def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")


def _derive_blockers(
    *,
    decision: str,
    preflight: dict[str, Any] | None,
    alerts_payload: dict[str, Any] | None,
    indexer_payload: dict[str, Any] | None,
    safe_payload: dict[str, Any] | None,
    railway_payload: dict[str, Any] | None,
) -> list[str]:
    blockers: list[str] = []
    if decision == "GO":
        # Keep automatic blockers strict in GO mode.
        if preflight and preflight.get("success") is not True:
            blockers.append("preflight_not_green")
        alerts_check = _extract_check(preflight, "alerts")
        if alerts_check and alerts_check.get("ok") is not True:
            blockers.append("alerts_check_not_green")
        if alerts_payload:
            items = ((alerts_payload.get("data") or {}).get("items")) if isinstance(alerts_payload.get("data"), dict) else None
            if isinstance(items, list):
                critical = [x for x in items if isinstance(x, dict) and str(x.get("severity") or "").lower() == "critical"]
                if critical:
                    blockers.append("critical_alerts_present")
        if indexer_payload:
            data = indexer_payload.get("data") if isinstance(indexer_payload.get("data"), dict) else indexer_payload
            if isinstance(data, dict):
                if bool(data.get("stale")):
                    blockers.append("indexer_stale")
                if bool(data.get("degraded")):
                    blockers.append("indexer_degraded")
        if safe_payload and safe_payload.get("ok") is False:
            blockers.append("safe_preflight_failed")
        if railway_payload and railway_payload.get("success") is False:
            blockers.append("railway_health_failed")
    return blockers


def _render_markdown(
    *,
    decision: str,
    reviewers: str,
    preflight: dict[str, Any] | None,
    alerts_payload: dict[str, Any] | None,
    indexer_payload: dict[str, Any] | None,
    safe_payload: dict[str, Any] | None,
    railway_payload: dict[str, Any] | None,
    smoke_notes: str,
    blockers: list[str],
) -> str:
    preflight_success = preflight.get("success") if isinstance(preflight, dict) else None
    alerts_check = _extract_check(preflight, "alerts")
    ops_smoke_check = _extract_check(preflight, "ops_smoke")
    cutover_check = _extract_check(preflight, "mainnet_cutover_preflight")
    health_check = _extract_check(preflight, "health")
    platform_capital_check = _extract_check(preflight, "platform_capital")

    critical_alert_count = None
    if alerts_check and isinstance(alerts_check.get("data"), dict):
        critical_alert_count = alerts_check["data"].get("critical_count")
    if critical_alert_count is None and alerts_payload:
        items = ((alerts_payload.get("data") or {}).get("items")) if isinstance(alerts_payload.get("data"), dict) else None
        if isinstance(items, list):
            critical_alert_count = len(
                [x for x in items if isinstance(x, dict) and str(x.get("severity") or "").lower() == "critical"]
            )

    indexer_stale = None
    indexer_degraded = None
    if indexer_payload:
        idx = indexer_payload.get("data") if isinstance(indexer_payload.get("data"), dict) else indexer_payload
        if isinstance(idx, dict):
            indexer_stale = bool(idx.get("stale"))
            indexer_degraded = bool(idx.get("degraded"))

    lines: list[str] = []
    lines.append("# Base Mainnet Go/No-Go Decision Record")
    lines.append("")
    lines.append(f"- timestamp_utc: `{_now_utc()}`")
    lines.append(f"- reviewers: `{reviewers}`")
    lines.append(f"- decision: `{decision}`")
    lines.append("")
    lines.append("## Readiness Snapshot")
    lines.append("")
    lines.append("| Signal | Value |")
    lines.append("|---|---|")
    lines.append(f"| preflight_success | `{_fmt_bool(bool(preflight_success) if preflight_success is not None else None)}` |")
    lines.append(f"| health_check_ok | `{_fmt_bool(bool(health_check.get('ok')) if health_check else None)}` |")
    lines.append(f"| alerts_check_ok | `{_fmt_bool(bool(alerts_check.get('ok')) if alerts_check else None)}` |")
    lines.append(
        f"| critical_alert_count | `{critical_alert_count if critical_alert_count is not None else 'unknown'}` |"
    )
    lines.append(f"| ops_smoke_ok | `{_fmt_bool(bool(ops_smoke_check.get('ok')) if ops_smoke_check else None)}` |")
    lines.append(f"| mainnet_cutover_preflight_ok | `{_fmt_bool(bool(cutover_check.get('ok')) if cutover_check else None)}` |")
    lines.append(
        f"| platform_capital_check_ok | `{_fmt_bool(bool(platform_capital_check.get('ok')) if platform_capital_check else None)}` |"
    )
    lines.append(f"| indexer_stale | `{_fmt_bool(indexer_stale)}` |")
    lines.append(f"| indexer_degraded | `{_fmt_bool(indexer_degraded)}` |")
    lines.append(f"| safe_preflight_ok | `{_fmt_bool(bool(safe_payload.get('ok')) if safe_payload else None)}` |")
    lines.append(f"| railway_health_ok | `{_fmt_bool(bool(railway_payload.get('success')) if railway_payload else None)}` |")
    lines.append("")
    lines.append("## Internal Smoke Evidence")
    lines.append("")
    lines.append(smoke_notes.strip() or "_not provided_")
    lines.append("")
    lines.append("## Blockers")
    lines.append("")
    if blockers:
        for b in blockers:
            lines.append(f"- `{_markdown_escape(b)}`")
    else:
        lines.append("- none")
    lines.append("")
    lines.append("## Next Action")
    lines.append("")
    if decision == "GO" and not blockers:
        lines.append("- Enable first external agents with low caps and active monitoring.")
    elif decision == "GO" and blockers:
        lines.append("- Decision/data mismatch: resolve blockers before public enablement.")
    else:
        lines.append("- Keep external agents disabled, fix blockers, re-run this report.")
    lines.append("")
    lines.append("## Evidence References")
    lines.append("")
    lines.append("- `prod_preflight_report.json`")
    lines.append("- `railway_health_report.json` (if available)")
    lines.append("- `safe_execution_preflight.json` (if available)")
    lines.append("- internal smoke tx list / operator notes")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate a final Base mainnet GO/NO_GO markdown record from preflight and ops evidence artifacts."
    )
    parser.add_argument("--decision", choices=["GO", "NO_GO"], default="NO_GO")
    parser.add_argument("--reviewers", default="operators")
    parser.add_argument("--preflight-json", default="")
    parser.add_argument("--alerts-json", default="")
    parser.add_argument("--indexer-json", default="")
    parser.add_argument("--safe-preflight-json", default="")
    parser.add_argument("--railway-health-json", default="")
    parser.add_argument("--internal-smoke-notes", default="", help="Short text summary of internal smoke evidence.")
    parser.add_argument("--internal-smoke-notes-file", default="", help="Path to markdown/text with internal smoke evidence.")
    parser.add_argument("--out", default="", help="Write markdown report to file (default: stdout).")
    parser.add_argument("--json-out", default="", help="Optional path to write machine-readable summary JSON.")
    args = parser.parse_args()

    smoke_notes = str(args.internal_smoke_notes or "").strip()
    if not smoke_notes and str(args.internal_smoke_notes_file or "").strip():
        smoke_notes = Path(args.internal_smoke_notes_file).expanduser().read_text(encoding="utf-8")

    preflight = _read_json(str(args.preflight_json or "").strip() or None)
    alerts_payload = _read_json(str(args.alerts_json or "").strip() or None)
    indexer_payload = _read_json(str(args.indexer_json or "").strip() or None)
    safe_payload = _read_json(str(args.safe_preflight_json or "").strip() or None)
    railway_payload = _read_json(str(args.railway_health_json or "").strip() or None)

    blockers = _derive_blockers(
        decision=str(args.decision),
        preflight=preflight,
        alerts_payload=alerts_payload,
        indexer_payload=indexer_payload,
        safe_payload=safe_payload,
        railway_payload=railway_payload,
    )

    report_md = _render_markdown(
        decision=str(args.decision),
        reviewers=str(args.reviewers),
        preflight=preflight,
        alerts_payload=alerts_payload,
        indexer_payload=indexer_payload,
        safe_payload=safe_payload,
        railway_payload=railway_payload,
        smoke_notes=smoke_notes,
        blockers=blockers,
    )

    if str(args.out or "").strip():
        Path(args.out).expanduser().write_text(report_md, encoding="utf-8")
    else:
        sys.stdout.write(report_md)

    if str(args.json_out or "").strip():
        payload = {
            "success": True,
            "decision": str(args.decision),
            "reviewers": str(args.reviewers),
            "generated_at": _now_utc(),
            "blockers": blockers,
            "sources": {
                "preflight_json": str(args.preflight_json or ""),
                "alerts_json": str(args.alerts_json or ""),
                "indexer_json": str(args.indexer_json or ""),
                "safe_preflight_json": str(args.safe_preflight_json or ""),
                "railway_health_json": str(args.railway_health_json or ""),
            },
        }
        Path(args.json_out).expanduser().write_text(json.dumps(payload, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")

    if str(args.decision) == "GO" and blockers:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
