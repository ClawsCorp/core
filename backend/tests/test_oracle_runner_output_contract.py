from __future__ import annotations

import json
from pathlib import Path

from src.oracle_runner import cli


class _FakeClient:
    def __init__(self, _config: object):
        self._responses = {
            "/api/v1/oracle/reconciliation/202501": {"ready": True, "delta_micro_usdc": 0},
            "/api/v1/oracle/settlement/202501": {"status": "ok"},
            "/api/v1/oracle/settlement/202501/deposit-profit": {
                "profit_month_id": "202501",
                "status": "submitted",
                "tx_hash": "0xdep",
                "blocked_reason": None,
                "idempotency_key": "deposit_profit:202501:123",
                "task_id": "txo_1",
                "amount_micro_usdc": 123,
            },
            "/api/v1/oracle/distributions/202501/create": {"status": "submitted", "tx_hash": "0xcreate"},
            "/api/v1/oracle/distributions/202501/execute": {"status": "submitted", "tx_hash": "0xexec"},
            "/api/v1/oracle/payouts/202501/sync": {"status": "ok", "executed_at": "2026-01-01T00:00:00Z"},
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
            "/api/v1/bounties/bty_123/evaluate-eligibility": {"status": "eligible_for_payout", "reasons": None},
            "/api/v1/bounties/bty_123/mark-paid": {"status": "paid", "blocked_reason": None},
            "/api/v1/oracle/project-capital-events": {
                "event_id": "pcap_1",
                "project_id": "proj_123",
                "delta_micro_usdc": 123,
                "source": "stake",
                "profit_month_id": None,
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
    monkeypatch.setenv("ORACLE_AUTO_MONTH", "202501")
    payload = tmp_path / "execute.json"
    payload.write_text(json.dumps({"stakers": ["0x1"], "staker_shares": [1], "authors": ["0x2"], "author_shares": [1]}))

    exit_code = cli.run(["run-month", "--execute-payload", str(payload)])

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


def test_evaluate_bounty_eligibility_json_flag(monkeypatch, capsys, tmp_path: Path) -> None:
    _setup_fake_runner(monkeypatch)
    payload = tmp_path / "elig.json"
    payload.write_text(
        json.dumps(
            {
                "pr_url": "https://example.com/pr/1",
                "merged": True,
                "merge_sha": "deadbeef",
                "required_approvals": 1,
                "required_checks": [{"name": "backend", "status": "success"}],
            }
        )
    )

    exit_code = cli.run(["evaluate-bounty-eligibility", "--bounty-id", "bty_123", "--payload", str(payload), "--json"])

    captured = capsys.readouterr()
    assert exit_code == 0
    data = json.loads(captured.out.strip())
    assert data["status"] == "eligible_for_payout"
    assert captured.err.strip() == ""


def test_mark_bounty_paid_without_json_writes_human_summary_to_stderr(monkeypatch, capsys) -> None:
    _setup_fake_runner(monkeypatch)

    exit_code = cli.run(["mark-bounty-paid", "--bounty-id", "bty_123", "--paid-tx-hash", "0xabc"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out.strip() == ""
    assert "status=paid" in captured.err


def test_project_reconcile_alias(monkeypatch, capsys) -> None:
    _setup_fake_runner(monkeypatch)

    exit_code = cli.run(["project-reconcile", "--project-id", "proj_123"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out.strip() == ""
    assert "ready=True" in captured.err


def test_project_capital_event_derived_idempotency_key_json(monkeypatch, capsys) -> None:
    _setup_fake_runner(monkeypatch)

    exit_code = cli.run(
        [
            "project-capital-event",
            "--project-id",
            "proj_123",
            "--delta-micro-usdc",
            "123",
            "--source",
            "stake",
            "--json",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    data = json.loads(captured.out.strip())
    assert data["event_id"] == "pcap_1"
    assert captured.err.strip() == ""


def test_deposit_profit_json_flag(monkeypatch, capsys) -> None:
    _setup_fake_runner(monkeypatch)

    exit_code = cli.run(["deposit-profit", "--month", "202501", "--json"])

    captured = capsys.readouterr()
    assert exit_code == 0
    data = json.loads(captured.out.strip())
    assert data["status"] == "submitted"
    assert data["tx_hash"] == "0xdep"
    assert captured.err.strip() == ""


def test_prune_operational_tables_json_flag(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        cli,
        "_prune_operational_rows",
        lambda **_: {
            "status": "ok",
            "audit_logs_deleted": 10,
            "oracle_nonces_deleted": 11,
            "project_capital_reconciliation_reports_deleted": 12,
            "project_revenue_reconciliation_reports_deleted": 13,
            "audit_log_cutoff": "2026-02-20T00:00:00+00:00",
            "nonce_cutoff": "2026-02-26T00:00:00+00:00",
            "reconciliation_cutoff": "2026-02-24T00:00:00+00:00",
        },
    )

    exit_code = cli.run(["prune-operational-tables", "--json"])

    captured = capsys.readouterr()
    assert exit_code == 0
    data = json.loads(captured.out.strip())
    assert data["status"] == "ok"
    assert data["audit_logs_deleted"] == 10
    assert data["project_revenue_reconciliation_reports_deleted"] == 13
    assert captured.err.strip() == ""


def test_run_project_month_stdout_json_and_stderr_progress(monkeypatch, capsys) -> None:
    _setup_fake_runner(monkeypatch)

    exit_code = cli.run(["run-project-month", "--project-id", "proj_123"])

    captured = capsys.readouterr()
    assert exit_code == 0
    stdout_lines = [line for line in captured.out.splitlines() if line.strip()]
    assert len(stdout_lines) == 1
    summary = json.loads(stdout_lines[0])
    assert summary["success"] is True
    assert summary["project_id"] == "proj_123"
    assert "reconciliation" in summary

    stderr = captured.err
    assert "stage=reconcile_project_capital status=start" in stderr
    assert "stage=reconcile_project_capital status=ok" in stderr


def test_git_worker_fails_when_open_pr_is_required_but_pr_creation_fails(monkeypatch, capsys, tmp_path: Path) -> None:
    class _FakeGitWorkerClient:
        def __init__(self, _config: object):
            self.claimed = False
            self.completed: list[dict[str, object]] = []

        def post(self, path: str, *, body_bytes: bytes, idempotency_key: str | None = None):
            if path == "/api/v1/oracle/git-outbox/claim-next":
                if self.claimed:
                    return type("Resp", (), {"data": {"data": {"task": None, "blocked_reason": "no_tasks"}}})()
                self.claimed = True
                return type(
                    "Resp",
                    (),
                    {
                        "data": {
                            "data": {
                                "task": {
                                    "task_id": "gto_test_1",
                                    "task_type": "create_app_surface_commit",
                                    "payload": {"slug": "demo-surface", "open_pr": True},
                                },
                                "blocked_reason": None,
                            }
                        }
                    },
                )()
            if path.endswith("/complete"):
                payload = json.loads(body_bytes.decode("utf-8"))
                self.completed.append(payload)
                return type("Resp", (), {"data": {"data": {"task_id": "gto_test_1"}}})()
            return type("Resp", (), {"data": {"data": {"ok": True}}})()

    fake_client = _FakeGitWorkerClient(object())

    monkeypatch.setattr(cli, "load_config_from_env", lambda: object())
    monkeypatch.setattr(cli, "OracleClient", lambda _config: fake_client)
    monkeypatch.setattr(cli, "_discover_repo_root", lambda _explicit: tmp_path)

    def _fake_run_local_cmd(args: list[str], *, cwd: Path) -> str:
        if args[:3] == ["git", "rev-parse", "HEAD"]:
            return "a" * 40
        if args[:3] == ["gh", "pr", "create"]:
            raise cli.OracleRunnerError("simulated_pr_create_failure")
        return ""

    monkeypatch.setattr(cli, "_run_local_cmd", _fake_run_local_cmd)

    exit_code = cli.run(["git-worker", "--json", "--worker-id", "test-worker", "--max-tasks", "1", "--repo-dir", str(tmp_path)])

    captured = capsys.readouterr()
    assert exit_code == 0
    data = json.loads(captured.out.strip())
    assert data["status"] == "ok"
    processed = data["processed"]
    assert len(processed) == 1
    assert processed[0]["status"] == "failed"
    assert processed[0]["error_hint"] == "simulated_pr_create_failure"
    assert fake_client.completed[-1]["status"] == "failed"
    assert fake_client.completed[-1]["error_hint"] == "simulated_pr_create_failure"


def test_git_worker_queues_auto_merge_when_requested(monkeypatch, capsys, tmp_path: Path) -> None:
    class _FakeGitWorkerClient:
        def __init__(self, _config: object):
            self.claimed = False
            self.completed: list[dict[str, object]] = []

        def post(self, path: str, *, body_bytes: bytes, idempotency_key: str | None = None):
            if path == "/api/v1/oracle/git-outbox/claim-next":
                if self.claimed:
                    return type("Resp", (), {"data": {"data": {"task": None, "blocked_reason": "no_tasks"}}})()
                self.claimed = True
                return type(
                    "Resp",
                    (),
                    {
                        "data": {
                            "data": {
                                "task": {
                                    "task_id": "gto_test_2",
                                    "task_type": "create_project_backend_artifact_commit",
                                    "payload": {
                                        "slug": "demo-artifact",
                                        "open_pr": True,
                                        "auto_merge": True,
                                        "merge_policy": {
                                            "required_checks": ["backend", "frontend"],
                                            "required_approvals": 0,
                                            "require_non_draft": True,
                                        },
                                    },
                                },
                                "blocked_reason": None,
                            }
                        }
                    },
                )()
            if path.endswith("/complete"):
                payload = json.loads(body_bytes.decode("utf-8"))
                self.completed.append(payload)
                return type("Resp", (), {"data": {"data": {"task_id": "gto_test_2"}}})()
            return type("Resp", (), {"data": {"data": {"ok": True}}})()

    fake_client = _FakeGitWorkerClient(object())
    commands: list[list[str]] = []

    monkeypatch.setattr(cli, "load_config_from_env", lambda: object())
    monkeypatch.setattr(cli, "OracleClient", lambda _config: fake_client)
    monkeypatch.setattr(cli, "_discover_repo_root", lambda _explicit: tmp_path)

    def _fake_run_local_cmd(args: list[str], *, cwd: Path) -> str:
        commands.append(args)
        if args[:3] == ["git", "rev-parse", "HEAD"]:
            return "b" * 40
        if args[:3] == ["gh", "pr", "create"]:
            return "https://github.com/ClawsCorp/core/pull/9999"
        if args[:3] == ["gh", "pr", "view"]:
            return json.dumps({"state": "OPEN", "isDraft": False, "reviewDecision": "APPROVED"})
        if args[:3] == ["gh", "pr", "checks"]:
            return json.dumps(
                [
                    {"name": "backend", "state": "pass"},
                    {"name": "frontend", "state": "pending"},
                ]
            )
        if args[:3] == ["gh", "pr", "merge"]:
            return ""
        return ""

    monkeypatch.setattr(cli, "_run_local_cmd", _fake_run_local_cmd)

    exit_code = cli.run(["git-worker", "--json", "--worker-id", "test-worker", "--max-tasks", "1", "--repo-dir", str(tmp_path)])

    captured = capsys.readouterr()
    assert exit_code == 0
    data = json.loads(captured.out.strip())
    processed = data["processed"]
    assert len(processed) == 1
    assert processed[0]["status"] == "succeeded"
    assert processed[0]["auto_merge"] is True
    assert processed[0]["auto_merge_queued"] is True
    assert processed[0]["merge_policy_error"] is None
    assert any(cmd[:3] == ["gh", "pr", "merge"] for cmd in commands)
    assert fake_client.completed[-1]["status"] == "succeeded"


def test_git_worker_fails_auto_merge_when_required_check_is_missing(monkeypatch, capsys, tmp_path: Path) -> None:
    class _FakeGitWorkerClient:
        def __init__(self, _config: object):
            self.claimed = False
            self.completed: list[dict[str, object]] = []

        def post(self, path: str, *, body_bytes: bytes, idempotency_key: str | None = None):
            if path == "/api/v1/oracle/git-outbox/claim-next":
                if self.claimed:
                    return type("Resp", (), {"data": {"data": {"task": None, "blocked_reason": "no_tasks"}}})()
                self.claimed = True
                return type(
                    "Resp",
                    (),
                    {
                        "data": {
                            "data": {
                                "task": {
                                    "task_id": "gto_test_3",
                                    "task_type": "create_app_surface_commit",
                                    "payload": {
                                        "slug": "demo-surface",
                                        "open_pr": True,
                                        "auto_merge": True,
                                        "merge_policy": {
                                            "required_checks": ["backend", "frontend"],
                                            "required_approvals": 0,
                                            "require_non_draft": True,
                                        },
                                    },
                                },
                                "blocked_reason": None,
                            }
                        }
                    },
                )()
            if path.endswith("/complete"):
                payload = json.loads(body_bytes.decode("utf-8"))
                self.completed.append(payload)
                return type("Resp", (), {"data": {"data": {"task_id": "gto_test_3"}}})()
            return type("Resp", (), {"data": {"data": {"ok": True}}})()

    fake_client = _FakeGitWorkerClient(object())
    commands: list[list[str]] = []

    monkeypatch.setattr(cli, "load_config_from_env", lambda: object())
    monkeypatch.setattr(cli, "OracleClient", lambda _config: fake_client)
    monkeypatch.setattr(cli, "_discover_repo_root", lambda _explicit: tmp_path)

    def _fake_run_local_cmd(args: list[str], *, cwd: Path) -> str:
        commands.append(args)
        if args[:3] == ["git", "rev-parse", "HEAD"]:
            return "c" * 40
        if args[:3] == ["gh", "pr", "create"]:
            return "https://github.com/ClawsCorp/core/pull/10000"
        if args[:3] == ["gh", "pr", "view"]:
            return json.dumps({"state": "OPEN", "isDraft": False, "reviewDecision": "APPROVED"})
        if args[:3] == ["gh", "pr", "checks"]:
            return json.dumps([{"name": "backend", "state": "pass"}])
        if args[:3] == ["gh", "pr", "merge"]:
            return ""
        return ""

    monkeypatch.setattr(cli, "_run_local_cmd", _fake_run_local_cmd)

    exit_code = cli.run(["git-worker", "--json", "--worker-id", "test-worker", "--max-tasks", "1", "--repo-dir", str(tmp_path)])

    captured = capsys.readouterr()
    assert exit_code == 0
    data = json.loads(captured.out.strip())
    processed = data["processed"]
    assert len(processed) == 1
    assert processed[0]["status"] == "failed"
    assert processed[0]["merge_policy_error"] == "merge_policy_checks_missing:frontend"
    assert processed[0]["auto_merge_queued"] is False
    assert not any(cmd[:3] == ["gh", "pr", "merge"] for cmd in commands)
    assert fake_client.completed[-1]["status"] == "failed"
    assert fake_client.completed[-1]["error_hint"] == "merge_policy_checks_missing:frontend"


class _FakeClientReconcileBlocked(_FakeClient):
    def __init__(self, _config: object):
        super().__init__(_config)
        self._responses["/api/v1/oracle/reconciliation/202501"] = {"ready": False, "blocked_reason": "balance_mismatch", "delta_micro_usdc": -1}


def test_run_month_blocked_reconcile_still_prints_single_json(monkeypatch, capsys, tmp_path: Path) -> None:
    monkeypatch.setattr(cli, "load_config_from_env", lambda: object())
    monkeypatch.setattr(cli, "OracleClient", _FakeClientReconcileBlocked)
    monkeypatch.setenv("ORACLE_AUTO_MONTH", "202501")

    payload = tmp_path / "execute.json"
    payload.write_text(json.dumps({"stakers": ["0x1"], "staker_shares": [1], "authors": ["0x2"], "author_shares": [1]}))

    exit_code = cli.run(["run-month", "--execute-payload", str(payload)])

    captured = capsys.readouterr()
    assert exit_code == 11
    stdout_lines = [line for line in captured.out.splitlines() if line.strip()]
    assert len(stdout_lines) == 1
    summary = json.loads(stdout_lines[0])
    assert summary["success"] is False
    assert summary["failed_step"] == "deposit_profit"


class _FakeClientTxWorkerRetry:
    def __init__(self, _config: object):
        self.claim_calls = 0
        self.complete_payloads: list[dict] = []

    def post(self, path: str, *, body_bytes: bytes, idempotency_key: str | None = None):
        if path == "/api/v1/oracle/tx-outbox/claim-next":
            self.claim_calls += 1
            if self.claim_calls == 1:
                task = {
                    "task_id": "txo_1",
                    "idempotency_key": "deposit_profit:202501:123",
                    "task_type": "deposit_profit",
                    "payload": {
                        "profit_month_id": "202501",
                        "amount_micro_usdc": 123,
                        "to_address": "0x00000000000000000000000000000000000000aa",
                        "idempotency_key": "deposit_profit:202501:123",
                    },
                    "tx_hash": None,
                    "status": "processing",
                    "attempts": 1,
                }
                return type("Resp", (), {"data": {"data": {"task": task, "blocked_reason": None}}})()
            return type("Resp", (), {"data": {"data": {"task": None, "blocked_reason": "no_tasks"}}})()

        if path.endswith("/update"):
            return type("Resp", (), {"data": {"data": {"ok": True}}})()

        if path.endswith("/complete"):
            payload = json.loads(body_bytes.decode("utf-8"))
            self.complete_payloads.append(payload)
            return type("Resp", (), {"data": {"data": {"ok": True}}})()

        raise AssertionError(f"unexpected POST path {path}")


def test_tx_worker_retryable_error_requeues_once(monkeypatch, capsys) -> None:
    from src.services import blockchain as blockchain_mod

    fake_client = _FakeClientTxWorkerRetry(object())
    monkeypatch.setattr(cli, "load_config_from_env", lambda: object())
    monkeypatch.setattr(cli, "OracleClient", lambda _config: fake_client)

    def _raise_retryable(*args, **kwargs):
        raise blockchain_mod.BlockchainTxError("rpc failed", error_hint="rpc_error")

    monkeypatch.setattr(blockchain_mod, "submit_usdc_transfer_tx", _raise_retryable)

    exit_code = cli.run(["tx-worker", "--max-tasks", "5", "--json"])

    captured = capsys.readouterr()
    assert exit_code == 0
    payload = json.loads(captured.out.strip())
    assert payload["status"] == "ok"
    assert len(payload["processed"]) == 1
    assert payload["processed"][0]["status"] == "retry_pending"
    assert fake_client.claim_calls == 1
    assert len(fake_client.complete_payloads) == 1
    assert fake_client.complete_payloads[0]["status"] == "pending"


class _FakeClientTxWorkerSafe:
    def __init__(self, _config: object):
        self.claim_calls = 0
        self.update_payloads: list[dict] = []
        self.complete_payloads: list[dict] = []
        self.record_payloads: list[tuple[str, dict]] = []

    def post(self, path: str, *, body_bytes: bytes, idempotency_key: str | None = None):
        if path == "/api/v1/oracle/tx-outbox/claim-next":
            self.claim_calls += 1
            if self.claim_calls == 1:
                task = {
                    "task_id": "txo_safe_1",
                    "idempotency_key": "create_distribution:202501:123",
                    "task_type": "create_distribution",
                    "payload": {
                        "profit_month_id": "202501",
                        "profit_month_value": 202501,
                        "profit_sum_micro_usdc": 123,
                        "idempotency_key": "create_distribution:202501:123",
                    },
                    "tx_hash": None,
                    "status": "processing",
                    "attempts": 1,
                }
                return type("Resp", (), {"data": {"data": {"task": task, "blocked_reason": None}}})()
            return type("Resp", (), {"data": {"data": {"task": None, "blocked_reason": "no_tasks"}}})()
        if path.endswith("/update"):
            self.update_payloads.append(json.loads(body_bytes.decode("utf-8")))
            return type("Resp", (), {"data": {"data": {"ok": True}}})()
        if path.endswith("/complete"):
            self.complete_payloads.append(json.loads(body_bytes.decode("utf-8")))
            return type("Resp", (), {"data": {"data": {"ok": True}}})()
        if path.endswith("/create/record"):
            self.record_payloads.append((path, json.loads(body_bytes.decode("utf-8"))))
            return type("Resp", (), {"data": {"data": {"ok": True}}})()
        raise AssertionError(f"unexpected POST path {path}")


def test_tx_worker_create_distribution_executes_via_safe_when_keys_available(monkeypatch, capsys) -> None:
    fake_client = _FakeClientTxWorkerSafe(object())
    monkeypatch.setattr(cli, "load_config_from_env", lambda: object())
    monkeypatch.setattr(cli, "OracleClient", lambda _config: fake_client)
    monkeypatch.setenv("SAFE_OWNER_ADDRESS", "0x00000000000000000000000000000000000000aa")
    monkeypatch.setenv("SAFE_OWNER_KEYS_FILE", "/tmp/safe-owners.json")

    from src.core.config import get_settings

    from src.services import blockchain as blockchain_mod

    get_settings.cache_clear()

    monkeypatch.setattr(
        blockchain_mod,
        "build_create_distribution_safe_tx",
        lambda **_: {
            "to_address": "0x00000000000000000000000000000000000000bb",
            "data": "0x1234",
            "value_wei": "0",
            "operation": 0,
            "safe_owner_address": "0x00000000000000000000000000000000000000aa",
        },
    )
    monkeypatch.setattr(blockchain_mod, "submit_safe_transaction", lambda **_: "0x" + "d" * 64)

    exit_code = cli.run(["tx-worker", "--max-tasks", "5", "--json"])
    get_settings.cache_clear()

    captured = capsys.readouterr()
    assert exit_code == 0
    payload = json.loads(captured.out.strip())
    assert payload["status"] == "pending"
    assert payload["processed"][0]["status"] == "succeeded"
    assert payload["processed"][0]["mode"] == "safe_exec"
    assert len(fake_client.record_payloads) == 1
    assert fake_client.complete_payloads[0]["status"] == "succeeded"
