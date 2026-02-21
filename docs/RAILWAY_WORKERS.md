# Railway Workers (No-Human Operator)

This repo supports running autonomy as multiple Railway services from the same GitHub repository.

## Services

1. `backend-api` (existing)
- Dockerfile: `backend/Dockerfile`
- Start: runs Alembic migrations and serves FastAPI.

2. `usdc-indexer`
- Dockerfile: `backend/Dockerfile.indexer`
- Purpose: continuously index on-chain USDC transfers into `observed_usdc_transfers` + update `indexer_cursors`.

3. `tx-worker`
- Dockerfile: `backend/Dockerfile.tx_worker`
- Purpose: continuously claim `tx_outbox` tasks from API and submit on-chain tx (idempotent).

4. `autonomy-loop`
- Dockerfile: `backend/Dockerfile.autonomy_loop`
- Purpose: continuously run automation calls:
  - sync observed transfers into ledgers
  - refresh project reconciliations
  - run platform month orchestration (`run-month auto`)

## Required Environment Variables

### Shared (all services)
- `DATABASE_URL`
- `ENV=production`

### API service (`backend/Dockerfile`)
- `ORACLE_HMAC_SECRET`
- `CORS_ORIGINS`
- `BASE_SEPOLIA_RPC_URL`
- `USDC_ADDRESS`
- `DIVIDEND_DISTRIBUTOR_CONTRACT_ADDRESS`
- `FUNDING_POOL_CONTRACT_ADDRESS` (recommended)
- `MARKETING_TREASURY_ADDRESS` (required for marketing reserve settlement)
- `TX_OUTBOX_ENABLED=true`
- `TX_OUTBOX_LOCK_TTL_SECONDS` (recommended)

### Indexer service (`backend/Dockerfile.indexer`)
- `DATABASE_URL`
- `BASE_SEPOLIA_RPC_URL`
- `USDC_ADDRESS`
- Recommended (so the indexer actually has at least one watched address on day 1):
  - `DIVIDEND_DISTRIBUTOR_CONTRACT_ADDRESS`
  - `FUNDING_POOL_CONTRACT_ADDRESS` (optional)
- Optional tuning:
  - `INDEXER_SLEEP_SECONDS` (default `10`)
  - `INDEXER_CONFIRMATIONS` (default `5`)
  - `INDEXER_LOOKBACK_BLOCKS` (default `500`)

### Tx worker service (`backend/Dockerfile.tx_worker`)
- `ORACLE_BASE_URL` (points to API service URL, e.g. `https://...railway.app`)
- `ORACLE_HMAC_SECRET`
- `BASE_SEPOLIA_RPC_URL`
- `USDC_ADDRESS`
- `DIVIDEND_DISTRIBUTOR_CONTRACT_ADDRESS`
- `ORACLE_SIGNER_PRIVATE_KEY`
- Optional:
  - `TX_WORKER_MAX_TASKS` (default `10`)
  - `TX_WORKER_SLEEP_SECONDS` (default `5`)
  - `CONTRACTS_DIR=/app/contracts` (default)
- Handles tx outbox types: `deposit_profit`, `deposit_marketing_fee`, `create_distribution`, `execute_distribution`.

### Autonomy loop service (`backend/Dockerfile.autonomy_loop`)
- `ORACLE_BASE_URL`
- `ORACLE_HMAC_SECRET`
- Optional:
  - `AUTONOMY_LOOP_SLEEP_SECONDS` (default `60`)
  - `ORACLE_AUTO_MONTH=YYYYMM` (only for deterministic override; normally unset)

## Recommended Setup Order

1. Deploy API service (migrations run here).
2. Deploy indexer service.
3. Deploy tx-worker service.
4. Deploy autonomy-loop service.

## How To Verify (Portal)

- Frontend: `/autonomy` should show:
  - indexer freshness (cursor updated)
  - reconciliation freshness for active projects
  - pending/failed tx_outbox tasks (if any)
