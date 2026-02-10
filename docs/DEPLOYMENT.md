# Deployment

## Backend (Railway)

This project deploys the backend service using `backend/Dockerfile` for deterministic Railway builds.

### 1) Create the Railway project

1. Push your branch to GitHub.
2. In Railway, click **New Project** → **Deploy from GitHub repo**.
3. Select this repository (`core`).
4. Keep the service root as repository root (`/workspace/core` equivalent in Railway).

### 2) Build and start settings

Railway should auto-read `railway.json`.

- Builder: `Dockerfile`
- Dockerfile Path: `backend/Dockerfile`
- Start command (only if you need to override the Dockerfile `CMD`):

```bash
uvicorn src.main:app --host 0.0.0.0 --port $PORT
```

The container `WORKDIR` is `/app/backend`, so `src.main:app` resolves without a `cd`.

- Healthcheck path:

```text
/api/v1/health
```

> Note: Alembic is present (`backend/alembic.ini`). If you need schema migrations for your environment, run `alembic -c backend/alembic.ini upgrade head` as a one-off release task before serving traffic.

### 3) Add required environment variables

Set all variables from `.env.example` in Railway service settings.

Required for backend runtime:

- `DATABASE_URL`
- `BASE_SEPOLIA_RPC_URL`
- `USDC_ADDRESS`
- `DIVIDEND_DISTRIBUTOR_CONTRACT_ADDRESS`
- `ORACLE_HMAC_SECRET`

Commonly set (recommended/optional depending on environment):

- `APP_VERSION`
- `ENV`
- `CORS_ORIGINS`
- `CHAIN_ID` (`84532` for Base Sepolia)
- `ORACLE_API_KEY`
- `ORACLE_SIGNER_PRIVATE_KEY`

### 4) Database service

If you do not already have a Postgres instance:

1. In Railway, click **New** → **Database** → **PostgreSQL**.
2. Copy the connection string into backend service variable `DATABASE_URL`.
3. Redeploy the backend service.

### 5) Deploy

1. Trigger deploy (automatic on push, or click **Deploy** manually).
2. Wait until the service reaches **Healthy** status.
3. Confirm `healthcheckPath` succeeds.

### 6) Verify the public API

Replace `<railway-url>` with your deployed domain.

```bash
curl -sS https://<railway-url>/api/v1/health
curl -sS https://<railway-url>/api/v1/stats
curl -sS https://<railway-url>/api/v1/projects
```

Minimal `/api/v1/health` checklist:

- HTTP returns `200`.
- JSON has keys: `status`, `version`, `timestamp`, `db`.
- `status` is `ok` or `degraded` (degraded can happen if DB is intentionally absent/misconfigured).
- `db` is `ok`, `unhealthy`, or `not_configured`.

### Troubleshooting

- **App fails to boot (`PORT`/bind issues):** Ensure start command includes `--host 0.0.0.0 --port ${PORT}` exactly.
- **Healthcheck fails:** Confirm Railway healthcheck path is `/api/v1/health` (not `/health`).
- **500 errors on API startup:** Verify all required environment variables are set and non-empty.
- **CORS blocked in portal:** Set `CORS_ORIGINS` to comma-separated frontend origins.
- **DB connectivity errors:** Re-check `DATABASE_URL`, network policy, and run Alembic upgrade when schema is behind.

## Contracts

From the repository root, deploy the `DividendDistributor` with environment variables set for the target network:

```bash
export USDC_ADDRESS=0x...
export TREASURY_WALLET_ADDRESS=0x...
export FOUNDER_WALLET_ADDRESS=0x...

npx --prefix contracts hardhat run scripts/deploy-dividend-distributor.js --network <network>
```

Deploy the `FundingPool` with the USDC address for the target network:

```bash
export USDC_ADDRESS=0x...

npx --prefix contracts hardhat run scripts/deploy-funding-pool.js --network <network>
```
