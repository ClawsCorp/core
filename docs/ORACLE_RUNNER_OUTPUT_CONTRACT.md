# Oracle Runner stdout/stderr Contract

This document defines the observable output contract for `oracle_runner` commands.

## Goal

Keep `stdout` pipeline-safe:
- machine-readable payloads only;
- human diagnostics/progress on `stderr`.

## Non-`run-month` commands

Commands:
- `reconcile`
- `create-distribution`
- `execute-distribution`
- `confirm-payout`
- `sync-payout`

Behavior:
- Without `--json`:
  - `stdout`: empty (no human summary)
  - `stderr`: human-readable key/value summary and diagnostics
- With `--json`:
  - `stdout`: exactly one JSON object
  - `stderr`: empty or minimal diagnostics

`--json` is supported both globally and after subcommand, including:

```bash
oracle_runner --json reconcile --month 202501
oracle_runner reconcile --month 202501 --json
```

## `run-month`

`run-month` always emits exactly one JSON object to `stdout` on every exit path.

- `stdout`: one JSON summary object (success and all failure exits)
- `stderr`: stage progress/human diagnostics

Stage coverage includes settlement to avoid `missing_settlement` flows:
- settlement
- reconcile
- create_distribution
- execute_distribution
- confirm_payout

## Exit-path consistency

For `run-month`, JSON-only `stdout` is preserved for success and non-success exits (including runner/config/request errors and step failures), making the command safe for shell pipelines and machine ingestion.
