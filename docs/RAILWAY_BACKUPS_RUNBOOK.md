# Railway Postgres Backups and Restore Runbook (MVP)

This is the minimum procedure to be able to recover from a bad deploy / schema issue without a human in the money-moving loop.

## Inputs

- `DATABASE_URL` for the Railway Postgres instance (with credentials)
- Local tools:
  - `pg_dump`
  - `pg_restore` (for custom format)
  - `psql`

## Backup (custom format)

1) Export a consistent snapshot

```bash
export DATABASE_URL='postgresql+psycopg://...'

# For pg_* tools, strip the SQLAlchemy driver if present.
export PG_URL="${DATABASE_URL/+psycopg/}"

mkdir -p backups
ts="$(date -u +%Y%m%dT%H%M%SZ)"
pg_dump --format=custom --no-owner --no-privileges --file "backups/core-${ts}.dump" "$PG_URL"
```

2) Export schema-only (human-readable diff)

```bash
pg_dump --schema-only --no-owner --no-privileges --file "backups/core-${ts}.sql" "$PG_URL"
```

## Restore (into a scratch DB)

1) Create a fresh empty database (local or temporary managed instance).

2) Restore the custom dump

```bash
export SCRATCH_PG_URL='postgresql://...'
pg_restore --no-owner --no-privileges --clean --if-exists --dbname "$SCRATCH_PG_URL" "backups/core-${ts}.dump"
```

3) Basic validation

```bash
psql "$SCRATCH_PG_URL" -c 'select count(*) from agents;'
psql "$SCRATCH_PG_URL" -c 'select count(*) from audit_log;'
psql "$SCRATCH_PG_URL" -c 'select count(*) from revenue_events;'
psql "$SCRATCH_PG_URL" -c 'select count(*) from expense_events;'
```

## Retention (MVP policy)

- Keep at least 14 daily backups.
- Keep at least 6 monthly backups.

## Notes

- Prefer provider-managed backups/snapshots when available; this runbook is the portable fallback.
- Do not store raw backups in Git or public buckets. Use encrypted storage.

