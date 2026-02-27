# Ops/Sec Baseline (MVP)

Goal: run ClawsCorp Core without a human operator in the money-moving loop, while still being safe to operate.

## Secret Scanning

CI:

- GitHub Actions already runs `secrets-scan`.

Local:

- Before pushing, run:
  - `scripts/check.sh`

Hard rules:

- Never log secrets (private keys, HMAC secrets, API keys).
- Keep `.env` files out of git (repo already ignores `.env*` except `.env.example`).

## SBOM / Dependency Hygiene

CI:

- GitHub Actions runs `sbom` to generate an SPDX JSON SBOM artifact on every PR.

Node:

- `npm --prefix frontend audit`
- `npm --prefix contracts audit`

Python:

- `python -m pip list` (inventory)
- Optional: add `pip-audit` later (toolchain decision).

## Backups

Postgres (Railway):

- Schedule daily backups via provider tooling where possible.
- Minimum runbook actions:
  - export schema + data
  - validate restore locally into a scratch DB

Runbook TODO:

- See `docs/RAILWAY_BACKUPS_RUNBOOK.md`.
- Prefer `python3 scripts/postgres_backup_drill.py` for repeatable backup/restore validation.
- Test emergency mode and key rotation using:
  - `docs/INCIDENT_RESPONSE_RUNBOOK.md`
  - `docs/ORACLE_KEY_ROTATION_RUNBOOK.md`

## Alerting

MVP alerts to wire (source: audit_log / reconciliation reports / tx status tables):

- `tx_failed` spikes
- `reconciliation_stale` (project capital, settlement, later project revenue)
- `nonce_replay` spikes (oracle nonces)
- audit insert failures (best-effort paths should not silently drop)

Implementation options:

1) Simple: a cron/automation job that calls public endpoints and posts to a channel.
2) Better: ship structured logs + metrics to a hosted observability stack.

Current baseline automation:
- `.github/workflows/prod-autonomy-check.yml` (daily + manual)
