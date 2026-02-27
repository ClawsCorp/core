# Railway Postgres Backups and Restore Runbook (MVP)

This is the minimum procedure to be able to recover from a bad deploy / schema issue without a human in the money-moving loop.

## Inputs

- `DATABASE_URL` for the Railway Postgres instance (with credentials)
- `SCRATCH_PG_URL` for an empty scratch database used for restore validation
- Local tools:
  - `pg_dump`
  - `pg_restore` (for custom format)
  - `psql`

## One-command drill (preferred)

Use the repository helper to run the whole drill and emit JSON:

```bash
python3 scripts/postgres_backup_drill.py \
  --database-url "$DATABASE_URL" \
  --scratch-url "$SCRATCH_PG_URL" \
  --output-dir backups
```

The command:

1) creates a custom-format dump,
2) creates a schema-only snapshot,
3) restores into the scratch DB,
4) validates row counts for core append-only tables.

If you only want to verify backup export (without restore yet):

```bash
python3 scripts/postgres_backup_drill.py \
  --database-url "$DATABASE_URL" \
  --skip-restore \
  --output-dir backups
```

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
- For a production readiness decision, prefer the scripted drill above over manual `pg_*` commands so results are repeatable.
