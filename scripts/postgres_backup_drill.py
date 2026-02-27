#!/usr/bin/env python3
# SPDX-License-Identifier: BSL-1.1

"""Portable Postgres backup/restore drill for ClawsCorp.

Creates a custom-format backup and schema snapshot from DATABASE_URL, then
optionally restores into a scratch database and validates a few core tables.
Outputs machine-readable JSON for CI/operator usage.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_VALIDATE_TABLES = (
    "agents",
    "audit_logs",
    "revenue_events",
    "expense_events",
)


@dataclass
class StepResult:
    name: str
    ok: bool
    detail: str
    data: dict[str, Any] | None = None


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _normalize_pg_url(url: str) -> str:
    text = str(url).strip()
    if not text:
        raise ValueError("empty database URL")
    if text.startswith("postgresql+"):
        scheme, rest = text.split("://", 1)
        base = scheme.split("+", 1)[0]
        return f"{base}://{rest}"
    return text


def _require_binary(name: str) -> str:
    resolved = shutil.which(name)
    if not resolved:
        raise RuntimeError(f"required binary not found: {name}")
    return resolved


def _run(cmd: list[str], *, timeout: int, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
    )


def _trim_lines(text: str, max_lines: int = 12) -> list[str]:
    lines = [line for line in (text or "").strip().splitlines() if line.strip()]
    return lines[-max_lines:]


def _dump_step(
    *,
    pg_dump_bin: str,
    source_url: str,
    output_dir: Path,
    timeout: int,
    env: dict[str, str],
) -> tuple[list[StepResult], Path | None, Path | None]:
    results: list[StepResult] = []
    stamp = _utc_timestamp()
    custom_path = output_dir / f"core-{stamp}.dump"
    schema_path = output_dir / f"core-{stamp}.sql"

    dump_cmd = [
        pg_dump_bin,
        "--format=custom",
        "--no-owner",
        "--no-privileges",
        "--file",
        str(custom_path),
        source_url,
    ]
    completed = _run(dump_cmd, timeout=timeout, env=env)
    dump_ok = completed.returncode == 0 and custom_path.exists()
    results.append(
        StepResult(
            name="backup_dump",
            ok=dump_ok,
            detail="custom-format backup created" if dump_ok else f"pg_dump failed with code={completed.returncode}",
            data={
                "path": str(custom_path),
                "stderr_tail": _trim_lines(completed.stderr),
            },
        )
    )
    if not dump_ok:
        return results, None, None

    schema_cmd = [
        pg_dump_bin,
        "--schema-only",
        "--no-owner",
        "--no-privileges",
        "--file",
        str(schema_path),
        source_url,
    ]
    completed = _run(schema_cmd, timeout=timeout, env=env)
    schema_ok = completed.returncode == 0 and schema_path.exists()
    results.append(
        StepResult(
            name="backup_schema",
            ok=schema_ok,
            detail="schema snapshot created" if schema_ok else f"schema dump failed with code={completed.returncode}",
            data={
                "path": str(schema_path),
                "stderr_tail": _trim_lines(completed.stderr),
            },
        )
    )
    if not schema_ok:
        return results, custom_path, None
    return results, custom_path, schema_path


def _restore_step(
    *,
    pg_restore_bin: str,
    psql_bin: str,
    scratch_url: str,
    custom_path: Path,
    validate_tables: tuple[str, ...],
    timeout: int,
    env: dict[str, str],
) -> list[StepResult]:
    results: list[StepResult] = []
    restore_cmd = [
        pg_restore_bin,
        "--no-owner",
        "--no-privileges",
        "--clean",
        "--if-exists",
        "--dbname",
        scratch_url,
        str(custom_path),
    ]
    completed = _run(restore_cmd, timeout=timeout, env=env)
    restore_ok = completed.returncode == 0
    results.append(
        StepResult(
            name="restore",
            ok=restore_ok,
            detail="custom dump restored into scratch DB" if restore_ok else f"pg_restore failed with code={completed.returncode}",
            data={"stderr_tail": _trim_lines(completed.stderr)},
        )
    )
    if not restore_ok:
        return results

    for table in validate_tables:
        query = f"select count(*) as row_count from {table};"
        completed = _run([psql_bin, scratch_url, "-t", "-A", "-c", query], timeout=timeout, env=env)
        ok = completed.returncode == 0
        count_text = (completed.stdout or "").strip()
        row_count: int | None
        try:
            row_count = int(count_text) if count_text else None
        except ValueError:
            row_count = None
            ok = False
        results.append(
            StepResult(
                name=f"validate_{table}",
                ok=ok,
                detail=f"validated row count for {table}" if ok else f"validation failed for {table}",
                data={
                    "row_count": row_count,
                    "stderr_tail": _trim_lines(completed.stderr),
                },
            )
        )
    return results


def run_drill(
    *,
    database_url: str,
    scratch_url: str | None,
    output_dir: str | None,
    keep_files: bool,
    skip_restore: bool,
    timeout_seconds: int,
) -> tuple[bool, list[StepResult], dict[str, Any]]:
    pg_dump_bin = _require_binary("pg_dump")
    pg_restore_bin = _require_binary("pg_restore")
    psql_bin = _require_binary("psql")

    source_url = _normalize_pg_url(database_url)
    scratch_pg_url = _normalize_pg_url(scratch_url) if scratch_url else None
    if not skip_restore and not scratch_pg_url:
        raise ValueError("SCRATCH_PG_URL (or --scratch-url) is required unless --skip-restore is set")

    cleanup_dir = False
    if output_dir:
        artifacts_dir = Path(output_dir).expanduser().resolve()
        artifacts_dir.mkdir(parents=True, exist_ok=True)
    else:
        artifacts_dir = Path(tempfile.mkdtemp(prefix="clawscorp-backup-drill-")).resolve()
        cleanup_dir = not keep_files

    env = os.environ.copy()
    env.setdefault("PGCONNECT_TIMEOUT", str(max(5, timeout_seconds)))
    results: list[StepResult] = []
    custom_path: Path | None = None
    schema_path: Path | None = None

    try:
        dump_results, custom_path, schema_path = _dump_step(
            pg_dump_bin=pg_dump_bin,
            source_url=source_url,
            output_dir=artifacts_dir,
            timeout=max(60, timeout_seconds * 4),
            env=env,
        )
        results.extend(dump_results)
        if custom_path and not skip_restore:
            results.extend(
                _restore_step(
                    pg_restore_bin=pg_restore_bin,
                    psql_bin=psql_bin,
                    scratch_url=scratch_pg_url or "",
                    custom_path=custom_path,
                    validate_tables=DEFAULT_VALIDATE_TABLES,
                    timeout=max(60, timeout_seconds * 4),
                    env=env,
                )
            )
        overall_ok = all(step.ok for step in results)
        meta = {
            "artifacts_dir": str(artifacts_dir),
            "custom_dump_path": str(custom_path) if custom_path else None,
            "schema_dump_path": str(schema_path) if schema_path else None,
            "skip_restore": bool(skip_restore),
            "cleanup_after_run": bool(cleanup_dir),
        }
        return overall_ok, results, meta
    finally:
        if cleanup_dir:
            shutil.rmtree(artifacts_dir, ignore_errors=True)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a Postgres backup/restore drill")
    parser.add_argument("--database-url", default=os.getenv("DATABASE_URL"), help="Source database URL (default: env DATABASE_URL)")
    parser.add_argument("--scratch-url", default=os.getenv("SCRATCH_PG_URL"), help="Scratch database URL for restore validation")
    parser.add_argument("--output-dir", help="Directory for backup artifacts (default: temp dir)")
    parser.add_argument("--keep-files", action="store_true", help="Keep temp artifacts when --output-dir is omitted")
    parser.add_argument("--skip-restore", action="store_true", help="Only create backup artifacts, skip restore validation")
    parser.add_argument("--timeout-seconds", type=int, default=30, help="Base timeout for each DB command")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if not args.database_url:
        payload = {"success": False, "error": "DATABASE_URL (or --database-url) is required"}
        print(json.dumps(payload, ensure_ascii=True, indent=2))
        return 2

    try:
        ok, steps, meta = run_drill(
            database_url=str(args.database_url),
            scratch_url=str(args.scratch_url) if args.scratch_url else None,
            output_dir=args.output_dir,
            keep_files=bool(args.keep_files),
            skip_restore=bool(args.skip_restore),
            timeout_seconds=max(5, int(args.timeout_seconds)),
        )
    except Exception as exc:
        payload = {"success": False, "error": str(exc)}
        print(json.dumps(payload, ensure_ascii=True, indent=2))
        return 1

    payload = {
        "success": bool(ok),
        "meta": meta,
        "steps": [
            {
                "name": step.name,
                "ok": step.ok,
                "detail": step.detail,
                "data": step.data,
            }
            for step in steps
        ],
    }
    print(json.dumps(payload, ensure_ascii=True, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
