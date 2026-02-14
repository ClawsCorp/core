from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

from .client import OracleClient, OracleRunnerError, load_config_from_env, to_json_bytes

_MONTH_RE = re.compile(r"^\d{6}$")


def _validate_month(month: str) -> str:
    if not _MONTH_RE.fullmatch(month):
        raise OracleRunnerError("--month must be in YYYYMM format.")
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

    create = subparsers.add_parser("create-distribution")
    create.add_argument("--month", required=True)
    create.add_argument("--json", action="store_true", help="Print machine-readable JSON output to stdout.")

    execute = subparsers.add_parser("execute-distribution")
    execute.add_argument("--month", required=True)
    execute.add_argument("--payload", required=True)
    execute.add_argument("--idempotency-key")
    execute.add_argument("--json", action="store_true", help="Print machine-readable JSON output to stdout.")

    confirm = subparsers.add_parser("confirm-payout")
    confirm.add_argument("--month", required=True)
    confirm.add_argument("--tx-hash")
    confirm.add_argument("--json", action="store_true", help="Print machine-readable JSON output to stdout.")

    sync = subparsers.add_parser("sync-payout")
    sync.add_argument("--month", required=True)
    sync.add_argument("--tx-hash")
    sync.add_argument("--json", action="store_true", help="Print machine-readable JSON output to stdout.")

    run_month = subparsers.add_parser("run-month")
    run_month.add_argument("--month", required=True)
    run_month.add_argument("--execute-payload", required=True)
    run_month.add_argument("--idempotency-key")
    # run-month always prints a single JSON summary to stdout, regardless of --json.
    run_month.add_argument("--json", action="store_true", help=argparse.SUPPRESS)

    tx_worker = subparsers.add_parser(
        "tx-worker",
        help="Process tx_outbox tasks by sending transactions out-of-band (MVP).",
    )
    tx_worker.add_argument("--worker-id", default="oracle_runner")
    tx_worker.add_argument("--max-tasks", type=int, default=1)
    tx_worker.add_argument("--json", action="store_true", help="Print machine-readable JSON output to stdout.")

    return parser


def _post_action(client: OracleClient, path: str, body_bytes: bytes, idempotency_key: str | None = None) -> dict[str, Any]:
    response = client.post(path, body_bytes=body_bytes, idempotency_key=idempotency_key)
    return _extract_data(response.data)


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
            month = _validate_month(args.month)
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

        if args.command == "create-distribution":
            month = _validate_month(args.month)
            data = _post_action(client, f"/api/v1/oracle/distributions/{month}/create", b"")
            if json_mode:
                _print_json(data)
            else:
                _print_fields(data, ["status", "tx_hash", "blocked_reason", "idempotency_key"])
            return 0

        if args.command == "execute-distribution":
            month = _validate_month(args.month)
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
            month = _validate_month(args.month)
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
            month = _validate_month(args.month)
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

        if args.command == "run-month":
            month = _validate_month(args.month)
            summary: dict[str, Any] = {"month": month, "success": False}

            try:
                _print_progress("settlement", "start")
                settlement = _post_action(client, f"/api/v1/oracle/settlement/{month}", b"")
                summary["settlement"] = settlement
                _print_progress("settlement", "ok")
            except OracleRunnerError as exc:
                _print_progress("settlement", "error", str(exc))
                summary["failed_step"] = "settlement"
                summary["error"] = str(exc)
                _print_json(summary)
                return 2

            try:
                _print_progress("reconcile", "start")
                rec = _post_action(client, f"/api/v1/oracle/reconciliation/{month}", b"")
                summary["reconcile"] = rec
            except OracleRunnerError as exc:
                _print_progress("reconcile", "error", str(exc))
                summary["failed_step"] = "reconcile"
                summary["error"] = str(exc)
                _print_json(summary)
                return 3

            if not rec.get("ready"):
                _print_progress("reconcile", "blocked")
                summary["failed_step"] = "reconcile"
                _print_json(summary)
                return 4
            _print_progress("reconcile", "ok")

            try:
                _print_progress("create_distribution", "start")
                create = _post_action(client, f"/api/v1/oracle/distributions/{month}/create", b"")
                summary["create_distribution"] = create
            except OracleRunnerError as exc:
                _print_progress("create_distribution", "error", str(exc))
                summary["failed_step"] = "create_distribution"
                summary["error"] = str(exc)
                _print_json(summary)
                return 5

            if create.get("status") == "blocked":
                _print_progress("create_distribution", "blocked")
                summary["failed_step"] = "create_distribution"
                _print_json(summary)
                return 6
            _print_progress("create_distribution", "ok")

            try:
                _print_progress("execute_distribution", "start")
                execute_body, execute_payload = _load_execute_payload(args.execute_payload)
                run_idempotency_key = args.idempotency_key or _derive_execute_idempotency_key(month, execute_payload)
                execute = _post_action(
                    client,
                    f"/api/v1/oracle/distributions/{month}/execute",
                    execute_body,
                    idempotency_key=run_idempotency_key,
                )
                summary["execute_distribution"] = execute
            except OracleRunnerError as exc:
                _print_progress("execute_distribution", "error", str(exc))
                summary["failed_step"] = "execute_distribution"
                summary["error"] = str(exc)
                _print_json(summary)
                return 7

            if execute.get("status") == "blocked":
                _print_progress("execute_distribution", "blocked")
                summary["failed_step"] = "execute_distribution"
                _print_json(summary)
                return 8
            _print_progress("execute_distribution", "ok")

            try:
                _print_progress("confirm_payout", "start")
                confirm = _post_action(
                    client,
                    f"/api/v1/oracle/payouts/{month}/confirm",
                    b"{}",
                )
                summary["confirm_payout"] = confirm
            except OracleRunnerError as exc:
                _print_progress("confirm_payout", "error", str(exc))
                summary["failed_step"] = "confirm_payout"
                summary["error"] = str(exc)
                _print_json(summary)
                return 9
            _print_progress("confirm_payout", "pending" if confirm.get("status") == "pending" else "ok")

            summary["success"] = True
            _print_json(summary)
            if confirm.get("status") == "pending":
                return 10
            return 0

        if args.command == "tx-worker":
            from src.services.blockchain import (
                BlockchainConfigError,
                BlockchainTxError,
                submit_usdc_transfer_tx,
                submit_create_distribution_tx,
                submit_execute_distribution_tx,
            )

            worker_id = str(args.worker_id).strip() or "oracle_runner"
            max_tasks = max(1, min(int(args.max_tasks), 50))
            processed: list[dict[str, Any]] = []

            for _ in range(max_tasks):
                claim_path = "/api/v1/oracle/tx-outbox/claim-next"
                claim_body = to_json_bytes({"worker_id": worker_id})
                claim_resp = client.post(claim_path, body_bytes=claim_body)

                claim_data = _extract_data(claim_resp.data)
                task = claim_data.get("task")
                blocked_reason = claim_data.get("blocked_reason")
                if not isinstance(task, dict):
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

            if json_mode:
                _print_json({"success": True, "command": command, "status": "ok", "processed": processed})
            else:
                _print_progress("tx_worker", "ok", detail=f"processed={len(processed)}")
            return 0

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
