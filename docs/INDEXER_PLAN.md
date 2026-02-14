# On-Chain Indexer (Plan)

Goal: reduce reliance on oracle ingestion where the chain is the source of truth.

MVP deliverable:

- A small worker that:
  - reads on-chain events / receipts for `DividendDistributor`
  - reads USDC `Transfer` events into/out of project treasury addresses
  - writes append-only `observed_*` rows in Postgres
  - reconciles observed rows with oracle-ingested rows (oracle remains fallback)

## Data Model (Draft)

Append-only tables (examples):

- `observed_usdc_transfers`:
  - `chain_id`, `tx_hash`, `log_index`, `block_number`, `from`, `to`, `amount_micro_usdc`, `observed_at`
- `observed_dividend_distributions`:
  - `chain_id`, `tx_hash`, `month`, `root_or_payload_hash`, `status`, `observed_at`

Uniqueness:

- `(chain_id, tx_hash, log_index)` should be unique for log-based tables.

## Worker Loop (Draft)

- Maintain cursor by `block_number` per chain.
- For each batch:
  - fetch logs
  - insert-or-ignore into observed tables (race-safe unique constraints)
  - update cursor

## Safety

- Read-only from chain, append-only to DB.
- Never moves money.

## Status (Implemented MVP)

As of 2026-02-14:

- Migration `0028_observed_usdc_transfers` adds:
  - `observed_usdc_transfers` (append-only, unique by `(chain_id, tx_hash, log_index)`)
  - `indexer_cursors` (per `(cursor_key, chain_id)` cursor)
- CLI (runs as a DB-writing worker):
  - `cd backend`
  - `PYTHONPATH=src python -m src.indexer.usdc_transfers`
  - Optional flags:
    - `--lookback-blocks 500`
    - `--confirmations 5`
    - `--from-block N --to-block M` (manual range)

Requirements:

- `DATABASE_URL` (Postgres) to write observed rows
- `BASE_SEPOLIA_RPC_URL` + `USDC_ADDRESS`

