# ClawsCorp Core Backend

## Environment

Set the following environment variables before running the API or Alembic:

- `APP_VERSION` (optional)
- `ENV` (optional)
- `CORS_ORIGINS` (optional, comma-separated)
- `DATABASE_URL` (required for database connectivity and migrations)

Example:

```bash
export DATABASE_URL="postgresql+psycopg://user:password@localhost:5432/clawscore"
```

## Alembic

Run migrations from the `backend` directory:

```bash
alembic -c alembic.ini current
alembic -c alembic.ini upgrade head
```
