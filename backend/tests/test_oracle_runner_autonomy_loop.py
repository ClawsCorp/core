from __future__ import annotations

import json

from src.oracle_runner import cli


class _FakeClientAutonomy:
    def __init__(self, _config: object):
        self.post_calls: list[str] = []
        # Minimal happy-path responses.
        self._post_responses: dict[str, dict] = {
            "/api/v1/oracle/project-capital-events/sync": {
                "transfers_seen": 1,
                "capital_events_inserted": 1,
                "projects_with_treasury_count": 1,
            },
            "/api/v1/oracle/billing/sync": {
                "transfers_seen": 0,
                "billing_events_inserted": 0,
                "revenue_events_inserted": 0,
            },
            "/api/v1/oracle/projects/proj_1/capital/reconciliation": {"ready": True, "delta_micro_usdc": 0},
            "/api/v1/oracle/projects/proj_1/revenue/reconciliation": {"ready": True, "delta_micro_usdc": 0},
            "/api/v1/oracle/marketing/settlement/deposit": {
                "status": "submitted",
                "tx_hash": None,
                "blocked_reason": None,
                "idempotency_key": "deposit_marketing_fee:100:0",
                "task_id": "txo_m_1",
                "amount_micro_usdc": 100,
                "accrued_total_micro_usdc": 100,
                "sent_total_micro_usdc": 0,
            },
            "/api/v1/oracle/settlement/202501": {"status": "ok"},
            "/api/v1/oracle/reconciliation/202501": {"ready": True, "delta_micro_usdc": 0},
            "/api/v1/oracle/settlement/202501/deposit-profit": {
                "profit_month_id": "202501",
                "status": "submitted",
                "tx_hash": "0xdep",
                "blocked_reason": None,
                "idempotency_key": "deposit_profit:202501:123",
                "task_id": "txo_1",
                "amount_micro_usdc": 123,
            },
            "/api/v1/oracle/settlement/202502/deposit-profit": {
                "profit_month_id": "202502",
                "status": "submitted",
                "tx_hash": "0xdep2",
                "blocked_reason": None,
                "idempotency_key": "deposit_profit:202502:456",
                "task_id": "txo_2",
                "amount_micro_usdc": 456,
            },
            "/api/v1/oracle/distributions/202501/create": {"status": "submitted", "tx_hash": "0xcreate"},
            "/api/v1/oracle/distributions/202501/execute/payload": {
                "status": "ok",
                "stakers": ["0x1"],
                "staker_shares": [1],
                "authors": ["0x2"],
                "author_shares": [1],
            },
            "/api/v1/oracle/distributions/202501/execute": {"status": "submitted", "tx_hash": "0xexec"},
            "/api/v1/oracle/payouts/202501/sync": {"status": "ok", "executed_at": "2026-01-01T00:00:00Z"},
            "/api/v1/oracle/payouts/202501/confirm": {"status": "confirmed", "tx_hash": "0xconfirm"},
        }

    def get(self, path: str):
        if path.startswith("/api/v1/projects"):
            return type(
                "Resp",
                (),
                {"data": {"success": True, "data": {"items": [{"project_id": "proj_1"}], "limit": 100, "offset": 0, "total": 1}}},
            )()
        if path.startswith("/api/v1/settlement/months"):
            return type(
                "Resp",
                (),
                {
                    "data": {
                        "success": True,
                        "data": {
                            "items": [
                                {
                                    "profit_month_id": "202502",
                                    "profit_sum_micro_usdc": 456,
                                    "delta_micro_usdc": -456,
                                    "blocked_reason": "balance_mismatch",
                                },
                                {
                                    "profit_month_id": "202501",
                                    "profit_sum_micro_usdc": 123,
                                    "delta_micro_usdc": 0,
                                    "blocked_reason": None,
                                },
                            ],
                            "limit": 24,
                            "offset": 0,
                            "total": 2,
                        },
                    }
                },
            )()
        raise AssertionError(f"unexpected GET path {path}")

    def post(self, path: str, *, body_bytes: bytes, idempotency_key: str | None = None):
        self.post_calls.append(path)
        data = self._post_responses.get(path)
        if data is None:
            raise AssertionError(f"unexpected POST path {path}")
        return type("Resp", (), {"data": {"data": data}})()


def test_autonomy_loop_once_prints_single_json(monkeypatch, capsys) -> None:
    monkeypatch.setattr(cli, "load_config_from_env", lambda: object())
    monkeypatch.setattr(cli, "OracleClient", _FakeClientAutonomy)
    monkeypatch.setenv("ORACLE_AUTO_MONTH", "202501")

    exit_code = cli.run(
        [
            "autonomy-loop",
            "--sync-project-capital",
            "--billing-sync",
            "--reconcile-projects",
            "--reconcile-project-revenue",
            "--marketing-deposit",
            "--run-month",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    lines = [line for line in captured.out.splitlines() if line.strip()]
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["command"] == "autonomy-loop"
    assert payload["month"] == "202501"
    assert payload["success"] is True
    assert "marketing_deposit" in payload
    assert payload["marketing_deposit"]["status"] == "submitted"
    assert "run_month" in payload
    assert payload["run_month"]["success"] is True
    assert "deposit_backlog" in payload
    assert payload["deposit_backlog"][0]["month"] == "202502"


def test_autonomy_loop_defaults_do_not_call_marketing_deposit(monkeypatch, capsys) -> None:
    monkeypatch.setattr(cli, "load_config_from_env", lambda: object())
    monkeypatch.setattr(cli, "OracleClient", _FakeClientAutonomy)
    monkeypatch.setenv("ORACLE_AUTO_MONTH", "202501")

    exit_code = cli.run(["autonomy-loop"])

    captured = capsys.readouterr()
    assert exit_code == 0
    payload = json.loads([line for line in captured.out.splitlines() if line.strip()][0])
    assert payload["command"] == "autonomy-loop"
    assert "marketing_deposit" not in payload


def test_autonomy_loop_can_run_prune_only(monkeypatch, capsys) -> None:
    monkeypatch.setattr(cli, "load_config_from_env", lambda: object())
    monkeypatch.setattr(cli, "OracleClient", _FakeClientAutonomy)
    monkeypatch.setenv("ORACLE_AUTO_MONTH", "202501")
    monkeypatch.setattr(
        cli,
        "_prune_operational_rows",
        lambda **_: {
            "status": "ok",
            "audit_logs_deleted": 2,
            "oracle_nonces_deleted": 3,
            "project_capital_reconciliation_reports_deleted": 4,
            "project_revenue_reconciliation_reports_deleted": 5,
            "audit_log_cutoff": "2026-02-20T00:00:00+00:00",
            "nonce_cutoff": "2026-02-26T00:00:00+00:00",
            "reconciliation_cutoff": "2026-02-24T00:00:00+00:00",
        },
    )

    exit_code = cli.run(["autonomy-loop", "--prune-operational-tables"])

    captured = capsys.readouterr()
    assert exit_code == 0
    payload = json.loads([line for line in captured.out.splitlines() if line.strip()][0])
    assert payload["command"] == "autonomy-loop"
    assert payload["success"] is True
    assert payload["prune_operational_tables"]["audit_logs_deleted"] == 2
    assert "sync_project_capital" not in payload
