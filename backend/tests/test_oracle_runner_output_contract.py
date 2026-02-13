from __future__ import annotations

import json
from pathlib import Path

from src.oracle_runner import cli


class _FakeClient:
    def __init__(self, _config: object):
        self._responses = {
            "/api/v1/oracle/reconciliation/202501": {"ready": True, "delta_micro_usdc": 0},
            "/api/v1/oracle/settlement/202501": {"status": "ok"},
            "/api/v1/oracle/distributions/202501/create": {"status": "submitted", "tx_hash": "0xcreate"},
            "/api/v1/oracle/distributions/202501/execute": {"status": "submitted", "tx_hash": "0xexec"},
            "/api/v1/oracle/payouts/202501/confirm": {"status": "confirmed", "tx_hash": "0xconfirm"},
            "/api/v1/oracle/projects/proj_123/capital/reconciliation": {
                "project_id": "proj_123",
                "treasury_address": "0xabc",
                "ledger_balance_micro_usdc": 1,
                "onchain_balance_micro_usdc": 1,
                "delta_micro_usdc": 0,
                "ready": True,
                "blocked_reason": None,
                "computed_at": "2026-01-01T00:00:00Z",
            },
        }

    def post(self, path: str, *, body_bytes: bytes, idempotency_key: str | None = None):
        data = self._responses[path]
        return type("Resp", (), {"data": {"data": data}})()


def _setup_fake_runner(monkeypatch):
    monkeypatch.setattr(cli, "load_config_from_env", lambda: object())
    monkeypatch.setattr(cli, "OracleClient", _FakeClient)


def test_run_month_stdout_json_and_stderr_progress(monkeypatch, capsys, tmp_path: Path) -> None:
    _setup_fake_runner(monkeypatch)
    payload = tmp_path / "execute.json"
    payload.write_text(json.dumps({"stakers": ["0x1"], "staker_shares": [1], "authors": ["0x2"], "author_shares": [1]}))

    exit_code = cli.run(["run-month", "--month", "202501", "--execute-payload", str(payload)])

    captured = capsys.readouterr()
    assert exit_code == 0
    stdout_lines = [line for line in captured.out.splitlines() if line.strip()]
    assert len(stdout_lines) == 1
    summary = json.loads(stdout_lines[0])
    assert summary["success"] is True
    assert summary["month"] == "202501"
    assert "settlement" in summary

    stderr = captured.err
    assert "stage=settlement status=start" in stderr
    assert "stage=settlement status=ok" in stderr
    assert "stage=reconcile status=start" in stderr
    assert "stage=create_distribution status=start" in stderr
    assert "stage=execute_distribution status=start" in stderr
    assert "stage=confirm_payout status=start" in stderr


def test_reconcile_json_flag_after_subcommand(monkeypatch, capsys) -> None:
    _setup_fake_runner(monkeypatch)

    exit_code = cli.run(["reconcile", "--month", "202501", "--json"])

    captured = capsys.readouterr()
    assert exit_code == 0
    payload = json.loads(captured.out.strip())
    assert payload["ready"] is True
    assert captured.err.strip() == ""


def test_reconcile_without_json_writes_human_summary_to_stderr(monkeypatch, capsys) -> None:
    _setup_fake_runner(monkeypatch)

    exit_code = cli.run(["reconcile", "--month", "202501"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out.strip() == ""
    assert "ready=True" in captured.err
    assert "delta_micro_usdc=0" in captured.err


def test_reconcile_project_capital_json_flag_after_subcommand(monkeypatch, capsys) -> None:
    _setup_fake_runner(monkeypatch)

    exit_code = cli.run(["reconcile-project-capital", "--project-id", "proj_123", "--json"])

    captured = capsys.readouterr()
    assert exit_code == 0
    payload = json.loads(captured.out.strip())
    assert payload["project_id"] == "proj_123"
    assert payload["ready"] is True
    assert captured.err.strip() == ""


def test_reconcile_project_capital_without_json_writes_human_summary_to_stderr(monkeypatch, capsys) -> None:
    _setup_fake_runner(monkeypatch)

    exit_code = cli.run(["reconcile-project-capital", "--project-id", "proj_123"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out.strip() == ""
    assert "ready=True" in captured.err
    assert "delta_micro_usdc=0" in captured.err
