from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

from .client import OracleClient, OracleRunnerError, load_config_from_env

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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="oracle_runner", description="Oracle month orchestration runner")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON output to stdout.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    reconcile = subparsers.add_parser("reconcile")
    reconcile.add_argument("--month", required=True)
    reconcile.add_argument("--json", action="store_true", help="Print machine-readable JSON output to stdout.")

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
