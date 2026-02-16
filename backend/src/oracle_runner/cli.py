from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timedelta, timezone
import os
import time
from pathlib import Path
from typing import Any

from .client import OracleClient, OracleRunnerError, load_config_from_env, to_json_bytes

_MONTH_RE = re.compile(r"^\d{6}$")


def _auto_month_utc_prev() -> str:
    override = os.getenv("ORACLE_AUTO_MONTH", "").strip()
    if override:
        if not _MONTH_RE.fullmatch(override):
            raise OracleRunnerError("ORACLE_AUTO_MONTH must be in YYYYMM format when set.")
        return override
    now = datetime.now(timezone.utc)
    first = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    # Previous month: subtract 1 day from the first of this month.
    prev = first - timedelta(days=1)
    return prev.strftime("%Y%m")


def _resolve_month_arg(raw: str | None) -> str:
    month = str(raw or "auto").strip()
    if month.lower() == "auto":
        return _auto_month_utc_prev()
    if not _MONTH_RE.fullmatch(month):
        raise OracleRunnerError("--month must be in YYYYMM format (or 'auto').")
    return month


def _extract_data(payload: dict[str, Any]) -> dict[str, Any]:
    data = payload.get("data")
    if isinstance(data, dict):
        return data
    return payload


def _print_fields(data: dict[str, Any], keys: list[str]) -> None:
    for key in keys:
        print(f"{key}={data.get(key)}", file=sys.stderr)


def _print_json(data: dict[str, Any]) -> None:
    print(json.dumps(data, ensure_ascii=True, sort_keys=True))


def _print_progress(stage: str, status: str, detail: str | None = None) -> None:
    # NOTE: `stage` and `status` are part of the stderr output contract (see docs).
    # `detail` is best-effort diagnostic text only and may change over time.
    suffix = f" detail={detail}" if detail else ""
    print(f"stage={stage} status={status}{suffix}", file=sys.stderr)


def _load_execute_payload(path: str) -> tuple[bytes, dict[str, Any]]:
    if path.strip().lower() == "auto":
        raise OracleRunnerError("Use build-execute-payload or run-month with --execute-payload auto.")
    payload_path = Path(path)
    if not payload_path.exists():
        raise OracleRunnerError(f"Execute payload file not found: {path}")
    try:
        raw = payload_path.read_bytes()
    except OSError as exc:
        raise OracleRunnerError(f"Failed to read execute payload file: {path}") from exc

    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise OracleRunnerError("Execute payload must be valid JSON.") from exc

    _validate_execute_payload(parsed)
    return raw, parsed


def _write_execute_payload_file(path: str, payload: dict[str, Any]) -> None:
    out_path = Path(path)
    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(payload, ensure_ascii=True, sort_keys=True), encoding="utf-8")
    except OSError as exc:
        raise OracleRunnerError(f"Failed to write payload file: {path}") from exc


def _load_json_payload(path: str) -> tuple[bytes, dict[str, Any]]:
    payload_path = Path(path)
    if not payload_path.exists():
        raise OracleRunnerError(f"Payload file not found: {path}")
    try:
        raw = payload_path.read_bytes()
    except OSError as exc:
        raise OracleRunnerError(f"Failed to read payload file: {path}") from exc

    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise OracleRunnerError("Payload must be valid JSON.") from exc
    if not isinstance(parsed, dict):
        raise OracleRunnerError("Payload must be a JSON object.")
    return raw, parsed


def _validate_execute_payload(payload: Any) -> None:
    if not isinstance(payload, dict):
        raise OracleRunnerError("Execute payload must be a JSON object.")

    required = ["stakers", "staker_shares", "authors", "author_shares"]
    for field in required:
        if field not in payload:
            raise OracleRunnerError(f"Execute payload missing required field: {field}")

    stakers = payload["stakers"]
    staker_shares = payload["staker_shares"]
    authors = payload["authors"]
    author_shares = payload["author_shares"]

    _validate_address_list("stakers", stakers)
    _validate_address_list("authors", authors)
    _validate_positive_int_list("staker_shares", staker_shares)
    _validate_positive_int_list("author_shares", author_shares)

    if len(stakers) != len(staker_shares):
        raise OracleRunnerError("stakers and staker_shares lengths must match.")
    if len(authors) != len(author_shares):
        raise OracleRunnerError("authors and author_shares lengths must match.")


def _validate_address_list(name: str, value: Any) -> None:
    if not isinstance(value, list):
        raise OracleRunnerError(f"{name} must be a list.")
    for idx, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            raise OracleRunnerError(f"{name}[{idx}] must be a non-empty string.")


def _validate_positive_int_list(name: str, value: Any) -> None:
    if not isinstance(value, list):
        raise OracleRunnerError(f"{name} must be a list.")
    for idx, item in enumerate(value):
        if not isinstance(item, int) or item <= 0:
            raise OracleRunnerError(f"{name}[{idx}] must be a positive integer.")


def _derive_execute_idempotency_key(month: str, payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, separators=(",", ":"), ensure_ascii=True, sort_keys=True)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return f"execute_distribution:{month}:{digest}"


def _derive_idempotency_key(prefix: str, payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, separators=(",", ":"), ensure_ascii=True, sort_keys=True)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return f"{prefix}:{digest}"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="oracle_runner", description="Oracle month orchestration runner")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON output to stdout.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    reconcile = subparsers.add_parser("reconcile")
    reconcile.add_argument("--month", required=True)
    reconcile.add_argument("--json", action="store_true", help="Print machine-readable JSON output to stdout.")

    reconcile_project_capital = subparsers.add_parser(
        "reconcile-project-capital",
        help="Run project capital on-chain vs ledger reconciliation for a project.",
    )
    reconcile_project_capital.add_argument("--project-id", required=True)
    reconcile_project_capital.add_argument("--json", action="store_true", help="Print machine-readable JSON output to stdout.")

    reconcile_project_revenue = subparsers.add_parser(
        "reconcile-project-revenue",
        help="Run project revenue on-chain vs ledger reconciliation for a project.",
    )
    reconcile_project_revenue.add_argument("--project-id", required=True)
    reconcile_project_revenue.add_argument("--json", action="store_true", help="Print machine-readable JSON output to stdout.")

    project_reconcile = subparsers.add_parser(
        "project-reconcile",
        help="Alias for reconcile-project-capital.",
    )
    project_reconcile.add_argument("--project-id", required=True)
    project_reconcile.add_argument("--json", action="store_true", help="Print machine-readable JSON output to stdout.")

    sync_project_capital = subparsers.add_parser(
        "sync-project-capital",
        help="Sync observed USDC treasury deposits into append-only project capital events (oracle HMAC protected).",
    )
    sync_project_capital.add_argument("--json", action="store_true", help="Print machine-readable JSON output to stdout.")

    project_capital_event = subparsers.add_parser(
        "project-capital-event",
        help="Append a project capital ledger event (oracle HMAC protected).",
    )
    project_capital_event.add_argument("--project-id", required=True)
    project_capital_event.add_argument("--delta-micro-usdc", required=True, type=int)
    project_capital_event.add_argument("--source", required=True)
    project_capital_event.add_argument("--profit-month-id")
    project_capital_event.add_argument("--evidence-tx-hash")
    project_capital_event.add_argument("--evidence-url")
    project_capital_event.add_argument("--idempotency-key")
    project_capital_event.add_argument("--json", action="store_true", help="Print machine-readable JSON output to stdout.")

    open_funding_round = subparsers.add_parser(
        "open-funding-round",
        help="Open a project funding round (oracle HMAC protected).",
    )
    open_funding_round.add_argument("--project-id", required=True)
    open_funding_round.add_argument("--title")
    open_funding_round.add_argument("--cap-micro-usdc", type=int)
    open_funding_round.add_argument("--idempotency-key")
    open_funding_round.add_argument("--json", action="store_true", help="Print machine-readable JSON output to stdout.")

    close_funding_round = subparsers.add_parser(
        "close-funding-round",
        help="Close a project funding round (oracle HMAC protected).",
    )
    close_funding_round.add_argument("--project-id", required=True)
    close_funding_round.add_argument("--round-id", required=True)
    close_funding_round.add_argument("--idempotency-key")
    close_funding_round.add_argument("--json", action="store_true", help="Print machine-readable JSON output to stdout.")

    run_project_month = subparsers.add_parser(
        "run-project-month",
        help="Project month orchestration (MVP): refresh project capital reconciliation and report readiness.",
    )
    run_project_month.add_argument("--project-id", required=True)
    # run-project-month always prints a single JSON summary to stdout, regardless of --json.
    run_project_month.add_argument("--json", action="store_true", help=argparse.SUPPRESS)

    evaluate_bounty = subparsers.add_parser(
        "evaluate-bounty-eligibility",
        help="Evaluate a bounty submission for payout eligibility (oracle HMAC protected).",
    )
    evaluate_bounty.add_argument("--bounty-id", required=True)
    evaluate_bounty.add_argument("--payload", required=True, help="Path to JSON payload for evaluate-eligibility.")
    evaluate_bounty.add_argument("--idempotency-key")
    evaluate_bounty.add_argument("--json", action="store_true", help="Print machine-readable JSON output to stdout.")

    mark_bounty_paid = subparsers.add_parser(
        "mark-bounty-paid",
        help="Mark a bounty as paid (oracle HMAC protected).",
    )
    mark_bounty_paid.add_argument("--bounty-id", required=True)
    mark_bounty_paid.add_argument("--paid-tx-hash", required=True)
    mark_bounty_paid.add_argument("--idempotency-key")
    mark_bounty_paid.add_argument("--json", action="store_true", help="Print machine-readable JSON output to stdout.")

    billing_sync = subparsers.add_parser(
        "billing-sync",
        help="Sync observed on-chain USDC transfers into billing_events/revenue_events (oracle HMAC protected).",
    )
    billing_sync.add_argument("--json", action="store_true", help="Print machine-readable JSON output to stdout.")

    create = subparsers.add_parser("create-distribution")
    create.add_argument("--month", required=True)
    create.add_argument("--json", action="store_true", help="Print machine-readable JSON output to stdout.")

    execute = subparsers.add_parser("execute-distribution")
    execute.add_argument("--month", required=True)
    execute.add_argument("--payload", required=True, help="Path to JSON file, or 'auto' to fetch from API.")
    execute.add_argument("--idempotency-key")
    execute.add_argument("--json", action="store_true", help="Print machine-readable JSON output to stdout.")

    build_payload = subparsers.add_parser(
        "build-execute-payload",
        help="Build a deterministic executeDistribution payload by querying the oracle API (HMAC protected).",
    )
    build_payload.add_argument("--month", required=True)
    build_payload.add_argument("--out", help="Write payload JSON to this file (required unless --json).")
    build_payload.add_argument("--json", action="store_true", help="Print machine-readable JSON output to stdout.")

    confirm = subparsers.add_parser("confirm-payout")
    confirm.add_argument("--month", required=True)
    confirm.add_argument("--tx-hash")
    confirm.add_argument("--json", action="store_true", help="Print machine-readable JSON output to stdout.")

    sync = subparsers.add_parser("sync-payout")
    sync.add_argument("--month", required=True)
    sync.add_argument("--tx-hash")
    sync.add_argument("--json", action="store_true", help="Print machine-readable JSON output to stdout.")

    deposit_profit = subparsers.add_parser(
        "deposit-profit",
        help="Enqueue/submit an autonomous profit top-up transfer into DividendDistributor for a given month (oracle HMAC protected).",
    )
    deposit_profit.add_argument("--month", required=True)
    deposit_profit.add_argument("--json", action="store_true", help="Print machine-readable JSON output to stdout.")

    run_month = subparsers.add_parser("run-month")
    run_month.add_argument(
        "--month",
        required=False,
        default="auto",
        help="Target profit month in YYYYMM format. Use 'auto' (default) to run for the previous month (UTC).",
    )
    run_month.add_argument(
        "--execute-payload",
        help="Path to execute payload JSON file, or 'auto' to fetch from API.",
        required=False,
        default="auto",
    )
    run_month.add_argument("--idempotency-key")
    # run-month always prints a single JSON summary to stdout, regardless of --json.
    run_month.add_argument("--json", action="store_true", help=argparse.SUPPRESS)

    tx_worker = subparsers.add_parser(
        "tx-worker",
        help="Process tx_outbox tasks by sending transactions out-of-band (MVP).",
    )
    tx_worker.add_argument("--worker-id", default="oracle_runner")
    tx_worker.add_argument("--max-tasks", type=int, default=1)
    tx_worker.add_argument("--loop", action="store_true", help="Run continuously until interrupted.")
    tx_worker.add_argument("--sleep-seconds", type=int, default=5, help="Sleep time between loop iterations when idle.")
    tx_worker.add_argument("--json", action="store_true", help="Print machine-readable JSON output to stdout.")

    autonomy_loop = subparsers.add_parser(
        "autonomy-loop",
        help="Continuously run sync + reconciliation + month orchestration (no human operator).",
    )
    autonomy_loop.add_argument("--loop", action="store_true", help="Run continuously until interrupted.")
    autonomy_loop.add_argument("--sleep-seconds", type=int, default=60, help="Sleep time between loop iterations.")
    autonomy_loop.add_argument(
        "--month",
        default="auto",
        help="Target profit month in YYYYMM format, or 'auto' (previous month UTC).",
    )
    autonomy_loop.add_argument(
        "--project-statuses",
        default="active,fundraising",
        help="Comma-separated project statuses to reconcile (public list filter).",
    )
    autonomy_loop.add_argument("--sync-project-capital", action="store_true", help="Call /oracle/project-capital-events/sync each loop.")
    autonomy_loop.add_argument("--billing-sync", action="store_true", help="Call /oracle/billing/sync each loop.")
    autonomy_loop.add_argument("--reconcile-projects", action="store_true", help="Refresh project capital reconciliation for active/fundraising projects.")
    autonomy_loop.add_argument("--reconcile-project-revenue", action="store_true", help="Refresh project revenue reconciliation where configured.")
    autonomy_loop.add_argument("--run-month", action="store_true", help="Run platform month flow each loop (idempotent).")
    autonomy_loop.add_argument(
        "--deposit-backlog-limit",
        type=int,
        default=3,
        help="After run-month, enqueue/submit deposit-profit for up to N under-funded platform months from settlement index (0 disables).",
    )
    autonomy_loop.add_argument(
        "--deposit-backlog-scan-limit",
        type=int,
        default=24,
        help="How many settlement months to scan for under-funded backlog.",
    )
    autonomy_loop.add_argument("--json", action="store_true", help="Print machine-readable JSON output to stdout (one object for --once).")

    return parser


def _post_action(client: OracleClient, path: str, body_bytes: bytes, idempotency_key: str | None = None) -> dict[str, Any]:
    response = client.post(path, body_bytes=body_bytes, idempotency_key=idempotency_key)
    return _extract_data(response.data)

def _get_action(client: OracleClient, path: str) -> dict[str, Any]:
    response = client.get(path)
    return _extract_data(response.data)


def _list_underfunded_months_for_deposit(
    client: OracleClient,
    *,
    scan_limit: int = 24,
    result_limit: int = 3,
) -> list[str]:
    """Return months that are under-funded (delta < 0, balance_mismatch) and need deposit-profit."""
    if scan_limit <= 0 or result_limit <= 0:
        return []

    data = _get_action(client, f"/api/v1/settlement/months?limit={int(scan_limit)}&offset=0")
    items = list(data.get("items") or []) if isinstance(data, dict) else []
    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        month = str(item.get("profit_month_id") or "").strip()
        if not _MONTH_RE.fullmatch(month):
            continue
        if month in seen:
            continue
        blocked_reason = str(item.get("blocked_reason") or "")
        try:
            delta = int(item.get("delta_micro_usdc") or 0)
            profit_sum = int(item.get("profit_sum_micro_usdc") or 0)
        except Exception:
            continue
        if blocked_reason == "balance_mismatch" and delta < 0 and profit_sum > 0:
            seen.add(month)
            out.append(month)
        if len(out) >= int(result_limit):
            break
    return out


def _run_month_flow(
    *,
    client: OracleClient,
    month: str,
    execute_payload_arg: str,
    idempotency_key: str | None,
    emit_progress: bool,
) -> tuple[int, dict[str, Any]]:
    summary: dict[str, Any] = {"month": month, "success": False}

    def prog(stage: str, status: str, detail: str | None = None) -> None:
        if emit_progress:
            _print_progress(stage, status, detail)

    try:
        prog("settlement", "start")
        settlement = _post_action(client, f"/api/v1/oracle/settlement/{month}", b"")
        summary["settlement"] = settlement
        prog("settlement", "ok")
    except OracleRunnerError as exc:
        prog("settlement", "error", str(exc))
        summary["failed_step"] = "settlement"
        summary["error"] = str(exc)
        return 2, summary

    try:
        prog("reconcile", "start")
        rec = _post_action(client, f"/api/v1/oracle/reconciliation/{month}", b"")
        summary["reconcile"] = rec
    except OracleRunnerError as exc:
        prog("reconcile", "error", str(exc))
        summary["failed_step"] = "reconcile"
        summary["error"] = str(exc)
        return 3, summary

    if not rec.get("ready"):
        blocked_reason = str(rec.get("blocked_reason") or "")
        delta = int(rec.get("delta_micro_usdc") or 0)  # distributor_balance - profit_sum

        # Autonomy: if we are under-funded (delta < 0), try to enqueue a top-up transfer.
        # This is the expected path for a fresh month where profit was computed but USDC
        # has not been deposited into DividendDistributor yet.
        if blocked_reason == "balance_mismatch" and delta < 0:
            try:
                prog("deposit_profit", "start")
                deposit = _post_action(client, f"/api/v1/oracle/settlement/{month}/deposit-profit", b"")
                summary["deposit_profit"] = deposit
            except OracleRunnerError as exc:
                prog("deposit_profit", "error", str(exc))
                summary["failed_step"] = "deposit_profit"
                summary["error"] = str(exc)
                return 4, summary

            if deposit.get("status") == "blocked":
                prog("deposit_profit", "blocked", str(deposit.get("blocked_reason") or "blocked"))
                summary["failed_step"] = "deposit_profit"
                return 4, summary

            # Deposit task is submitted/queued; wait for tx-worker and then rerun run-month.
            prog("deposit_profit", "pending", str(deposit.get("task_id") or deposit.get("tx_hash") or "submitted"))
            summary["failed_step"] = "deposit_profit"
            return 11, summary

        prog("reconcile", "blocked", blocked_reason or None)
        summary["failed_step"] = "reconcile"
        return 4, summary

    prog("reconcile", "ok")

    # Reconciliation is strict-ready, so deposit-profit should normally be a no-op/blocked(already_funded).
    try:
        prog("deposit_profit", "start")
        deposit = _post_action(client, f"/api/v1/oracle/settlement/{month}/deposit-profit", b"")
        summary["deposit_profit"] = deposit
        prog("deposit_profit", "ok" if deposit.get("status") != "blocked" else "blocked", str(deposit.get("blocked_reason") or "ok"))
    except OracleRunnerError as exc:
        prog("deposit_profit", "error", str(exc))
        summary["failed_step"] = "deposit_profit"
        summary["error"] = str(exc)
        return 4, summary

    try:
        prog("create_distribution", "start")
        create = _post_action(client, f"/api/v1/oracle/distributions/{month}/create", b"")
        summary["create_distribution"] = create
    except OracleRunnerError as exc:
        prog("create_distribution", "error", str(exc))
        summary["failed_step"] = "create_distribution"
        summary["error"] = str(exc)
        return 5, summary

    if create.get("status") == "blocked":
        prog("create_distribution", "blocked")
        summary["failed_step"] = "create_distribution"
        return 6, summary
    prog("create_distribution", "ok")

    try:
        if str(execute_payload_arg).strip().lower() == "auto":
            prog("build_execute_payload", "start")
            built = _post_action(client, f"/api/v1/oracle/distributions/{month}/execute/payload", b"{}")
            summary["build_execute_payload"] = built
            if built.get("status") != "ok":
                prog("build_execute_payload", "blocked")
                summary["failed_step"] = "build_execute_payload"
                return 7, summary
            prog("build_execute_payload", "ok")
            execute_payload = {
                "stakers": list(built.get("stakers") or []),
                "staker_shares": list(built.get("staker_shares") or []),
                "authors": list(built.get("authors") or []),
                "author_shares": list(built.get("author_shares") or []),
            }
            _validate_execute_payload(execute_payload)
            execute_body = json.dumps(
                execute_payload, separators=(",", ":"), ensure_ascii=True, sort_keys=True
            ).encode("utf-8")
        else:
            execute_body, execute_payload = _load_execute_payload(execute_payload_arg)

        prog("execute_distribution", "start")
        run_idempotency_key = idempotency_key or _derive_execute_idempotency_key(month, execute_payload)
        execute = _post_action(
            client,
            f"/api/v1/oracle/distributions/{month}/execute",
            execute_body,
            idempotency_key=run_idempotency_key,
        )
        summary["execute_distribution"] = execute
    except OracleRunnerError as exc:
        prog("execute_distribution", "error", str(exc))
        summary["failed_step"] = "execute_distribution"
        summary["error"] = str(exc)
        return 8, summary

    if summary["execute_distribution"].get("status") == "blocked":
        prog("execute_distribution", "blocked")
        summary["failed_step"] = "execute_distribution"
        return 9, summary
    prog("execute_distribution", "ok")

    try:
        prog("sync_payout", "start")
        sync = _post_action(
            client,
            f"/api/v1/oracle/payouts/{month}/sync",
            b"{}",
        )
        summary["sync_payout"] = sync
        prog("sync_payout", "ok" if sync.get("status") != "blocked" else "blocked", str(sync.get("blocked_reason") or "ok"))
    except OracleRunnerError as exc:
        prog("sync_payout", "error", str(exc))
        summary["failed_step"] = "sync_payout"
        summary["error"] = str(exc)
        return 9, summary

    try:
        prog("confirm_payout", "start")
        confirm = _post_action(
            client,
            f"/api/v1/oracle/payouts/{month}/confirm",
            b"{}",
        )
        summary["confirm_payout"] = confirm
    except OracleRunnerError as exc:
        prog("confirm_payout", "error", str(exc))
        summary["failed_step"] = "confirm_payout"
        summary["error"] = str(exc)
        return 9, summary

    prog("confirm_payout", "pending" if confirm.get("status") == "pending" else "ok")
    summary["success"] = True
    if confirm.get("status") == "pending":
        return 10, summary
    return 0, summary


def run(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    json_mode = bool(getattr(args, "json", False))
    command = getattr(args, "command", "")

    def _print_error_json(exc: OracleRunnerError) -> None:
        _print_json({"success": False, "command": command, "error": str(exc)})

    try:
        config = load_config_from_env()
        client = OracleClient(config)

        if args.command == "reconcile":
            month = _resolve_month_arg(args.month)
            data = _post_action(client, f"/api/v1/oracle/reconciliation/{month}", b"")
            if json_mode:
                _print_json(data)
            else:
                _print_fields(data, ["ready", "blocked_reason", "delta_micro_usdc", "distributor_balance_micro_usdc", "computed_at"])
            return 0

        if args.command == "reconcile-project-capital":
            project_id = str(args.project_id).strip()
            if not project_id:
                raise OracleRunnerError("--project-id is required.")
            data = _post_action(client, f"/api/v1/oracle/projects/{project_id}/capital/reconciliation", b"")
            if json_mode:
                _print_json(data)
            else:
                _print_fields(data, ["ready", "blocked_reason", "delta_micro_usdc", "onchain_balance_micro_usdc", "ledger_balance_micro_usdc", "computed_at"])
            return 0

        if args.command == "reconcile-project-revenue":
            project_id = str(args.project_id).strip()
            if not project_id:
                raise OracleRunnerError("--project-id is required.")
            data = _post_action(client, f"/api/v1/oracle/projects/{project_id}/revenue/reconciliation", b"")
            if json_mode:
                _print_json(data)
            else:
                _print_fields(data, ["ready", "blocked_reason", "delta_micro_usdc", "onchain_balance_micro_usdc", "ledger_balance_micro_usdc", "computed_at"])
            return 0

        if args.command == "project-reconcile":
            project_id = str(args.project_id).strip()
            if not project_id:
                raise OracleRunnerError("--project-id is required.")
            data = _post_action(client, f"/api/v1/oracle/projects/{project_id}/capital/reconciliation", b"")
            if json_mode:
                _print_json(data)
            else:
                _print_fields(data, ["ready", "blocked_reason", "delta_micro_usdc", "onchain_balance_micro_usdc", "ledger_balance_micro_usdc", "computed_at"])
            return 0

        if args.command == "sync-project-capital":
            data = _post_action(client, "/api/v1/oracle/project-capital-events/sync", b"")
            if json_mode:
                _print_json(data)
            else:
                _print_fields(data, ["projects_with_treasury_count", "transfers_seen", "capital_events_inserted"])
            return 0

        if args.command == "project-capital-event":
            project_id = str(args.project_id).strip()
            if not project_id:
                raise OracleRunnerError("--project-id is required.")
            source = str(args.source).strip()
            if not source:
                raise OracleRunnerError("--source is required.")

            payload: dict[str, Any] = {
                "project_id": project_id,
                "delta_micro_usdc": int(args.delta_micro_usdc),
                "source": source,
                "idempotency_key": args.idempotency_key or "",
                "profit_month_id": args.profit_month_id,
                "evidence_tx_hash": args.evidence_tx_hash,
                "evidence_url": args.evidence_url,
            }
            # Remove nulls to keep canonical key stable.
            payload = {k: v for k, v in payload.items() if v is not None}
            if not payload.get("idempotency_key"):
                derived = dict(payload)
                derived.pop("idempotency_key", None)
                payload["idempotency_key"] = _derive_idempotency_key("project_capital_event", derived)

            body_bytes = json.dumps(payload, separators=(",", ":"), ensure_ascii=True, sort_keys=True).encode("utf-8")
            data = _post_action(client, "/api/v1/oracle/project-capital-events", body_bytes, idempotency_key=payload["idempotency_key"])
            if json_mode:
                _print_json(data)
            else:
                # API returns the public event shape under data.
                _print_fields(data, ["event_id", "project_id", "delta_micro_usdc", "source", "profit_month_id"])
            return 0

        if args.command == "open-funding-round":
            project_id = str(args.project_id).strip()
            if not project_id:
                raise OracleRunnerError("--project-id is required.")

            payload: dict[str, Any] = {
                "idempotency_key": args.idempotency_key or "",
                "title": (str(args.title).strip() if args.title is not None else None),
                "cap_micro_usdc": (int(args.cap_micro_usdc) if args.cap_micro_usdc is not None else None),
            }
            payload = {k: v for k, v in payload.items() if v is not None}
            if not payload.get("idempotency_key"):
                derived = dict(payload)
                derived.pop("idempotency_key", None)
                payload["idempotency_key"] = _derive_idempotency_key(f"open_funding_round:{project_id}", derived)

            body_bytes = json.dumps(payload, separators=(",", ":"), ensure_ascii=True, sort_keys=True).encode("utf-8")
            data = _post_action(
                client,
                f"/api/v1/oracle/projects/{project_id}/funding-rounds",
                body_bytes,
                idempotency_key=str(payload["idempotency_key"]),
            )
            if json_mode:
                _print_json(data)
            else:
                # API returns round under data when success.
                _print_fields(data, ["round_id", "status", "cap_micro_usdc"])
            return 0

        if args.command == "close-funding-round":
            project_id = str(args.project_id).strip()
            if not project_id:
                raise OracleRunnerError("--project-id is required.")
            round_id = str(args.round_id).strip()
            if not round_id:
                raise OracleRunnerError("--round-id is required.")

            payload: dict[str, Any] = {"idempotency_key": args.idempotency_key or ""}
            if not payload.get("idempotency_key"):
                payload["idempotency_key"] = _derive_idempotency_key(f"close_funding_round:{project_id}:{round_id}", {})

            body_bytes = json.dumps(payload, separators=(",", ":"), ensure_ascii=True, sort_keys=True).encode("utf-8")
            data = _post_action(
                client,
                f"/api/v1/oracle/projects/{project_id}/funding-rounds/{round_id}/close",
                body_bytes,
                idempotency_key=str(payload["idempotency_key"]),
            )
            if json_mode:
                _print_json(data)
            else:
                _print_fields(data, ["round_id", "status"])
            return 0

        if args.command == "run-project-month":
            project_id = str(args.project_id).strip()
            if not project_id:
                raise OracleRunnerError("--project-id is required.")

            summary: dict[str, Any] = {"project_id": project_id, "success": False}
            try:
                _print_progress("reconcile_project_capital", "start")
                rec = _post_action(client, f"/api/v1/oracle/projects/{project_id}/capital/reconciliation", b"")
                summary["reconciliation"] = rec
            except OracleRunnerError as exc:
                _print_progress("reconcile_project_capital", "error", str(exc))
                summary["failed_step"] = "reconcile_project_capital"
                summary["error"] = str(exc)
                _print_json(summary)
                return 1

            if not rec.get("ready"):
                _print_progress("reconcile_project_capital", "blocked")
                summary["failed_step"] = "reconcile_project_capital"
                _print_json(summary)
                return 2

            _print_progress("reconcile_project_capital", "ok")
            summary["success"] = True
            _print_json(summary)
            return 0

        if args.command == "evaluate-bounty-eligibility":
            bounty_id = str(args.bounty_id).strip()
            if not bounty_id:
                raise OracleRunnerError("--bounty-id is required.")
            body_bytes, _ = _load_json_payload(args.payload)
            idempotency_key = getattr(args, "idempotency_key", None)
            data = _post_action(
                client,
                f"/api/v1/bounties/{bounty_id}/evaluate-eligibility",
                body_bytes,
                idempotency_key=idempotency_key,
            )
            if json_mode:
                _print_json(data)
            else:
                _print_fields(data, ["status", "reasons"])
            return 0

        if args.command == "mark-bounty-paid":
            bounty_id = str(args.bounty_id).strip()
            if not bounty_id:
                raise OracleRunnerError("--bounty-id is required.")
            paid_tx_hash = str(args.paid_tx_hash).strip()
            if not paid_tx_hash:
                raise OracleRunnerError("--paid-tx-hash is required.")
            body_bytes = json.dumps({"paid_tx_hash": paid_tx_hash}, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
            idempotency_key = getattr(args, "idempotency_key", None)
            data = _post_action(
                client,
                f"/api/v1/bounties/{bounty_id}/mark-paid",
                body_bytes,
                idempotency_key=idempotency_key,
            )
            if json_mode:
                _print_json(data)
            else:
                _print_fields(data, ["status", "blocked_reason"])
            return 0

        if args.command == "billing-sync":
            data = _post_action(client, "/api/v1/oracle/billing/sync", b"{}")
            if json_mode:
                _print_json(data)
            else:
                _print_fields(data, ["transfers_seen", "billing_events_inserted", "revenue_events_inserted"])
            return 0

        if args.command == "create-distribution":
            month = _resolve_month_arg(args.month)
            data = _post_action(client, f"/api/v1/oracle/distributions/{month}/create", b"")
            if json_mode:
                _print_json(data)
            else:
                _print_fields(data, ["status", "tx_hash", "blocked_reason", "idempotency_key"])
            return 0

        if args.command == "build-execute-payload":
            month = _resolve_month_arg(args.month)
            out_path = str(getattr(args, "out", "") or "").strip()
            if not json_mode and not out_path:
                raise OracleRunnerError("--out is required unless --json is used.")

            data = _post_action(client, f"/api/v1/oracle/distributions/{month}/execute/payload", b"{}")
            status = str(data.get("status") or "")

            payload = {
                "stakers": list(data.get("stakers") or []),
                "staker_shares": list(data.get("staker_shares") or []),
                "authors": list(data.get("authors") or []),
                "author_shares": list(data.get("author_shares") or []),
            }
            _validate_execute_payload(payload)

            if out_path:
                _write_execute_payload_file(out_path, payload)

            if json_mode:
                _print_json(
                    {
                        "success": status == "ok",
                        "command": command,
                        "month": month,
                        "status": status,
                        "blocked_reason": data.get("blocked_reason"),
                        "notes": data.get("notes") or [],
                        "payload": payload,
                        "out": out_path or None,
                    }
                )
            else:
                _print_fields(data, ["status", "blocked_reason"])
                if out_path:
                    _print_progress(
                        "build_execute_payload",
                        "ok" if status == "ok" else "blocked",
                        detail=out_path,
                    )
            return 0 if status == "ok" else 2

        if args.command == "execute-distribution":
            month = _resolve_month_arg(args.month)
            if str(args.payload).strip().lower() == "auto":
                built = _post_action(client, f"/api/v1/oracle/distributions/{month}/execute/payload", b"{}")
                payload = {
                    "stakers": list(built.get("stakers") or []),
                    "staker_shares": list(built.get("staker_shares") or []),
                    "authors": list(built.get("authors") or []),
                    "author_shares": list(built.get("author_shares") or []),
                }
                _validate_execute_payload(payload)
                parsed = payload
                body_bytes = json.dumps(payload, separators=(",", ":"), ensure_ascii=True, sort_keys=True).encode("utf-8")
            else:
                body_bytes, parsed = _load_execute_payload(args.payload)
            idempotency_key = args.idempotency_key or _derive_execute_idempotency_key(month, parsed)
            data = _post_action(
                client,
                f"/api/v1/oracle/distributions/{month}/execute",
                body_bytes,
                idempotency_key=idempotency_key,
            )
            if json_mode:
                _print_json(data)
            else:
                _print_fields(data, ["status", "tx_hash", "blocked_reason", "idempotency_key"])
            return 0

        if args.command == "confirm-payout":
            month = _resolve_month_arg(args.month)
            body = {} if args.tx_hash is None else {"tx_hash": args.tx_hash}
            data = _post_action(
                client,
                f"/api/v1/oracle/payouts/{month}/confirm",
                json.dumps(body, separators=(",", ":")).encode("utf-8"),
            )
            if json_mode:
                _print_json(data)
            else:
                _print_fields(data, ["status", "tx_hash", "blocked_reason", "idempotency_key", "confirmed_at", "failed_at"])
            return 0

        if args.command == "sync-payout":
            month = _resolve_month_arg(args.month)
            body = {} if args.tx_hash is None else {"tx_hash": args.tx_hash}
            data = _post_action(
                client,
                f"/api/v1/oracle/payouts/{month}/sync",
                json.dumps(body, separators=(",", ":")).encode("utf-8"),
            )
            if json_mode:
                _print_json(data)
            else:
                _print_fields(data, ["status", "tx_hash", "blocked_reason", "idempotency_key", "executed_at"])
            return 0

        if args.command == "deposit-profit":
            month = _resolve_month_arg(args.month)
            data = _post_action(client, f"/api/v1/oracle/settlement/{month}/deposit-profit", b"")
            if json_mode:
                _print_json(data)
            else:
                _print_fields(
                    data,
                    [
                        "status",
                        "tx_hash",
                        "blocked_reason",
                        "idempotency_key",
                        "task_id",
                        "amount_micro_usdc",
                    ],
                )
            return 0

        if args.command == "run-month":
            month = _resolve_month_arg(args.month)
            exit_code, summary = _run_month_flow(
                client=client,
                month=month,
                execute_payload_arg=str(args.execute_payload),
                idempotency_key=args.idempotency_key,
                emit_progress=True,
            )
            _print_json(summary)
            return exit_code

        if args.command == "autonomy-loop":
            if bool(args.loop) and json_mode:
                raise OracleRunnerError("--loop is not compatible with --json (streaming mode).")

            sleep_seconds = max(1, int(args.sleep_seconds))

            # Default to "do everything" if user didn't specify any actions.
            wants_any = any(
                [
                    bool(args.sync_project_capital),
                    bool(args.billing_sync),
                    bool(args.reconcile_projects),
                    bool(args.reconcile_project_revenue),
                    bool(args.run_month),
                ]
            )
            if not wants_any:
                args.sync_project_capital = True
                args.billing_sync = True
                args.reconcile_projects = True
                args.reconcile_project_revenue = True
                args.run_month = True

            while True:
                # Re-resolve month every cycle so long-running services naturally roll over
                # when the calendar month changes (for --month auto).
                month = _resolve_month_arg(getattr(args, "month", "auto"))
                cycle: dict[str, Any] = {
                    "success": True,
                    "command": command,
                    "month": month,
                }

                try:
                    if bool(args.sync_project_capital):
                        _print_progress("sync_project_capital", "start")
                        cycle["sync_project_capital"] = _post_action(client, "/api/v1/oracle/project-capital-events/sync", b"{}")
                        _print_progress("sync_project_capital", "ok")

                    if bool(args.billing_sync):
                        _print_progress("billing_sync", "start")
                        cycle["billing_sync"] = _post_action(client, "/api/v1/oracle/billing/sync", b"{}")
                        _print_progress("billing_sync", "ok")

                    if bool(args.reconcile_projects) or bool(args.reconcile_project_revenue):
                        _print_progress("list_projects", "start")
                        statuses = [s.strip() for s in str(args.project_statuses).split(",") if s.strip()]
                        project_ids: list[str] = []
                        seen_projects: set[str] = set()
                        for st in statuses:
                            projects_payload = _get_action(client, f"/api/v1/projects?status={st}&limit=100&offset=0")
                            items = list((projects_payload.get("items") or [])) if isinstance(projects_payload, dict) else []
                            for p in items:
                                if not isinstance(p, dict):
                                    continue
                                pid = str(p.get("project_id") or "").strip()
                                if not pid or pid in seen_projects:
                                    continue
                                seen_projects.add(pid)
                                project_ids.append(pid)
                        _print_progress("list_projects", "ok", detail=f"statuses={len(statuses)} projects={len(project_ids)}")
                        reconciled: list[dict[str, Any]] = []
                        for pid in project_ids:
                            if bool(args.reconcile_projects):
                                rep = _post_action(client, f"/api/v1/oracle/projects/{pid}/capital/reconciliation", b"{}")
                                reconciled.append({"project_id": pid, "capital": rep})
                            if bool(args.reconcile_project_revenue):
                                rep = _post_action(client, f"/api/v1/oracle/projects/{pid}/revenue/reconciliation", b"{}")
                                # Attach to last entry if present.
                                if reconciled and reconciled[-1].get("project_id") == pid:
                                    reconciled[-1]["revenue"] = rep
                                else:
                                    reconciled.append({"project_id": pid, "revenue": rep})
                        cycle["projects_reconciled"] = reconciled

                    if bool(args.run_month):
                        exit_code, rm = _run_month_flow(
                            client=client,
                            month=month,
                            execute_payload_arg="auto",
                            idempotency_key=None,
                            emit_progress=True,
                        )
                        cycle["run_month_exit_code"] = exit_code
                        cycle["run_month"] = rm
                        if exit_code not in (0, 10, 11, 4, 6, 7, 9):
                            cycle["success"] = False

                    backlog_limit = max(0, int(args.deposit_backlog_limit))
                    backlog_scan_limit = max(1, int(args.deposit_backlog_scan_limit))
                    if bool(args.run_month) and backlog_limit > 0:
                        try:
                            backlog_months = _list_underfunded_months_for_deposit(
                                client,
                                scan_limit=backlog_scan_limit,
                                result_limit=backlog_limit + 1,
                            )
                        except OracleRunnerError as exc:
                            cycle["success"] = False
                            cycle["deposit_backlog_error"] = str(exc)
                            _print_progress("deposit_backlog", "error", str(exc))
                            backlog_months = []

                        # Avoid duplicate call for month already handled by run-month.
                        backlog_months = [m for m in backlog_months if m != month][:backlog_limit]
                        backlog_results: list[dict[str, Any]] = []
                        for m in backlog_months:
                            try:
                                _print_progress("deposit_backlog", "start", detail=m)
                                dep = _post_action(client, f"/api/v1/oracle/settlement/{m}/deposit-profit", b"")
                                backlog_results.append({"month": m, "result": dep})
                                dstatus = str(dep.get("status") or "")
                                if dstatus == "blocked":
                                    _print_progress(
                                        "deposit_backlog",
                                        "blocked",
                                        detail=f"{m}:{dep.get('blocked_reason')}",
                                    )
                                else:
                                    _print_progress("deposit_backlog", "ok", detail=f"{m}:{dstatus or 'submitted'}")
                            except OracleRunnerError as exc:
                                cycle["success"] = False
                                backlog_results.append({"month": m, "error": str(exc)})
                                _print_progress("deposit_backlog", "error", detail=f"{m}:{exc}")
                        if backlog_results:
                            cycle["deposit_backlog"] = backlog_results

                except OracleRunnerError as exc:
                    cycle["success"] = False
                    cycle["error"] = str(exc)
                    _print_progress("autonomy_loop", "error", str(exc))

                # One JSON per cycle (JSONL-friendly). In non-loop mode, we print once and exit.
                _print_json(cycle)
                if not bool(args.loop):
                    return 0 if cycle.get("success") else 1
                time.sleep(sleep_seconds)

        if args.command == "tx-worker":
            from src.services.blockchain import (
                BlockchainConfigError,
                BlockchainTxError,
                submit_usdc_transfer_tx,
                submit_create_distribution_tx,
                submit_execute_distribution_tx,
            )

            if bool(args.loop) and json_mode:
                raise OracleRunnerError("--loop is not compatible with --json (streaming mode).")

            worker_id = str(args.worker_id).strip() or "oracle_runner"
            max_tasks = max(1, min(int(args.max_tasks), 50))
            sleep_seconds = max(1, int(args.sleep_seconds))

            processed: list[dict[str, Any]] = []
            while True:
                processed_this_loop = 0
                for _ in range(max_tasks):
                    claim_path = "/api/v1/oracle/tx-outbox/claim-next"
                    claim_body = to_json_bytes({"worker_id": worker_id})
                    claim_resp = client.post(claim_path, body_bytes=claim_body)

                    claim_data = _extract_data(claim_resp.data)
                    task = claim_data.get("task")
                    blocked_reason = claim_data.get("blocked_reason")
                    if not isinstance(task, dict):
                        if bool(args.loop):
                            _print_progress("tx_worker", "pending", detail=str(blocked_reason or "no_tasks"))
                            break
                        if json_mode:
                            _print_json(
                                {
                                    "success": True,
                                    "command": command,
                                    "status": "pending",
                                    "blocked_reason": blocked_reason,
                                    "processed": processed,
                                }
                            )
                        else:
                            _print_progress("tx_worker", "pending", detail=str(blocked_reason or "no_tasks"))
                        return 0

                    task_id = str(task.get("task_id") or "")
                    task_type = str(task.get("task_type") or "")
                    payload = task.get("payload") if isinstance(task.get("payload"), dict) else {}
                    idem = str(task.get("idempotency_key") or payload.get("idempotency_key") or "")
                    existing_tx_hash = str(task.get("tx_hash") or "")

                    def _update(tx_hash: str | None, result: dict[str, Any] | None) -> None:
                        update_path = f"/api/v1/oracle/tx-outbox/{task_id}/update"
                        client.post(
                            update_path,
                            body_bytes=to_json_bytes({"tx_hash": tx_hash, "result": result}),
                        )

                    def _complete(status: str, error_hint: str | None) -> None:
                        complete_path = f"/api/v1/oracle/tx-outbox/{task_id}/complete"
                        client.post(
                            complete_path,
                            body_bytes=to_json_bytes(
                                {
                                    "status": status,
                                    "error_hint": error_hint,
                                }
                            ),
                        )

                    try:
                        if task_type == "create_distribution":
                            profit_month_id = str(payload.get("profit_month_id") or "")
                            profit_month_value = int(payload.get("profit_month_value"))
                            profit_sum = int(payload.get("profit_sum_micro_usdc"))
                            tx_hash = existing_tx_hash or submit_create_distribution_tx(
                                profit_month_value=profit_month_value,
                                total_profit_micro_usdc=profit_sum,
                            )
                            # Persist early so we can resume after a crash.
                            _update(tx_hash, {"stage": "submitted"})
                            client.post(
                                f"/api/v1/oracle/distributions/{profit_month_id}/create/record",
                                body_bytes=to_json_bytes(
                                    {
                                        "idempotency_key": idem,
                                        "profit_sum_micro_usdc": profit_sum,
                                        "tx_hash": tx_hash,
                                    }
                                ),
                            )
                            _update(tx_hash, {"stage": "recorded"})
                            _complete("succeeded", None)
                            processed.append(
                                {
                                    "task_id": task_id,
                                    "task_type": task_type,
                                    "status": "succeeded",
                                    "tx_hash": tx_hash,
                                }
                            )
                            processed_this_loop += 1
                            if bool(args.loop):
                                _print_progress("tx_worker_task", "ok", detail=f"{task_type} {task_id}")
                            continue

                        if task_type == "execute_distribution":
                            profit_month_id = str(payload.get("profit_month_id") or "")
                            profit_month_value = int(payload.get("profit_month_value"))
                            stakers = list(payload.get("stakers") or [])
                            staker_shares = list(payload.get("staker_shares") or [])
                            authors = list(payload.get("authors") or [])
                            author_shares = list(payload.get("author_shares") or [])
                            total_profit = int(payload.get("total_profit_micro_usdc"))
                            stakers_count = int(payload.get("stakers_count"))
                            authors_count = int(payload.get("authors_count"))

                            tx_hash = existing_tx_hash or submit_execute_distribution_tx(
                                profit_month_value=profit_month_value,
                                stakers=stakers,
                                staker_shares=staker_shares,
                                authors=authors,
                                author_shares=author_shares,
                            )
                            _update(tx_hash, {"stage": "submitted"})
                            client.post(
                                f"/api/v1/oracle/distributions/{profit_month_id}/execute/record",
                                body_bytes=to_json_bytes(
                                    {
                                        "idempotency_key": idem,
                                        "tx_hash": tx_hash,
                                        "total_profit_micro_usdc": total_profit,
                                        "stakers_count": stakers_count,
                                        "authors_count": authors_count,
                                    }
                                ),
                            )
                            _update(tx_hash, {"stage": "recorded"})
                            _complete("succeeded", None)
                            processed.append(
                                {
                                    "task_id": task_id,
                                    "task_type": task_type,
                                    "status": "succeeded",
                                    "tx_hash": tx_hash,
                                }
                            )
                            processed_this_loop += 1
                            if bool(args.loop):
                                _print_progress("tx_worker_task", "ok", detail=f"{task_type} {task_id}")
                            continue

                        if task_type == "deposit_profit":
                            profit_month_id = str(payload.get("profit_month_id") or "")
                            amount = int(payload.get("amount_micro_usdc"))
                            to_address = str(payload.get("to_address") or "")

                            tx_hash = existing_tx_hash or submit_usdc_transfer_tx(
                                to_address=to_address,
                                amount_micro_usdc=amount,
                            )
                            _update(tx_hash, {"stage": "submitted"})
                            # No additional record endpoint needed; reconciliation is the source of truth.
                            _update(tx_hash, {"stage": "submitted_only"})
                            _complete("succeeded", None)
                            processed.append(
                                {
                                    "task_id": task_id,
                                    "task_type": task_type,
                                    "status": "succeeded",
                                    "tx_hash": tx_hash,
                                    "profit_month_id": profit_month_id,
                                    "amount_micro_usdc": amount,
                                }
                            )
                            processed_this_loop += 1
                            if bool(args.loop):
                                _print_progress("tx_worker_task", "ok", detail=f"{task_type} {task_id}")
                            continue

                        _complete("failed", "unknown_task_type")
                        processed.append(
                            {
                                "task_id": task_id,
                                "task_type": task_type,
                                "status": "failed",
                                "error_hint": "unknown_task_type",
                            }
                        )
                        processed_this_loop += 1
                        if bool(args.loop):
                            _print_progress("tx_worker_task", "error", detail=f"{task_type} {task_id} unknown_task_type")
                    except (BlockchainConfigError, BlockchainTxError) as exc:
                        hint = getattr(exc, "error_hint", None) or "tx_error"
                        _update(existing_tx_hash or None, {"stage": "failed", "error_hint": hint})
                        _complete("failed", hint)
                        processed.append(
                            {
                                "task_id": task_id,
                                "task_type": task_type,
                                "status": "failed",
                                "error_hint": hint,
                            }
                        )
                        processed_this_loop += 1
                        if bool(args.loop):
                            _print_progress("tx_worker_task", "error", detail=f"{task_type} {task_id} {hint}")

                if not bool(args.loop):
                    if json_mode:
                        _print_json({"success": True, "command": command, "status": "ok", "processed": processed})
                    else:
                        _print_progress("tx_worker", "ok", detail=f"processed={len(processed)}")
                    return 0

                # Loop mode: avoid unbounded memory growth.
                processed.clear()
                if processed_this_loop == 0:
                    time.sleep(sleep_seconds)

        parser.error("Unknown command")
    except OracleRunnerError as exc:
        # For machine mode (and for run-month always), keep stdout JSON-only.
        if command == "run-month" or json_mode:
            _print_error_json(exc)
        else:
            print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(run())
