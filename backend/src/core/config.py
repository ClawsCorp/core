# SPDX-License-Identifier: BSL-1.1

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import os


def _split_origins(value: str) -> list[str]:
    return [origin.strip() for origin in value.split(",") if origin.strip()]


def _optional_int_env(name: str) -> int | None:
    value = os.getenv(name, "").strip()
    if not value:
        return None
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer.") from exc


def _normalize_database_url(url: str) -> str:
    """
    Railway Postgres often provides DATABASE_URL as `postgresql://...` (no driver).
    SQLAlchemy may then try to use `psycopg2`, which we do not install (we use psycopg v3).
    Normalize to an explicit psycopg driver when the URL is a plain Postgres URL.
    """
    url = url.strip()
    if not url:
        return url

    # Heroku/Railway style alias.
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://") :]

    # If a driver is already specified (postgresql+...), leave it alone.
    if url.startswith("postgresql+"):
        return url

    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://") :]

    return url


@dataclass(frozen=True)
class Settings:
    app_version: str
    env: str
    cors_origins: list[str]
    database_url: str | None
    oracle_hmac_secret: str | None
    base_sepolia_rpc_url: str | None
    usdc_address: str | None
    dividend_distributor_contract_address: str | None
    funding_pool_contract_address: str | None
    marketing_treasury_address: str | None
    safe_owner_address: str | None
    oracle_signer_private_key: str | None
    contracts_dir: str
    oracle_request_ttl_seconds: int
    oracle_clock_skew_seconds: int
    oracle_accept_legacy_signatures: bool
    governance_quorum_min_votes: int
    governance_approval_bps: int
    governance_discussion_hours: int
    governance_voting_hours: int
    governance_discussion_minutes: int | None
    governance_voting_minutes: int | None
    project_capital_reconciliation_max_age_seconds: int
    project_revenue_reconciliation_max_age_seconds: int
    tx_outbox_lock_ttl_seconds: int
    tx_outbox_pending_max_age_seconds: int
    tx_outbox_processing_max_age_seconds: int
    git_outbox_pending_max_age_seconds: int
    git_outbox_processing_max_age_seconds: int
    indexer_cursor_max_age_seconds: int
    discussions_create_thread_max_per_minute: int
    discussions_create_post_max_per_minute: int
    discussions_create_thread_max_per_day: int
    discussions_create_post_max_per_day: int
    agents_register_max_per_minute: int
    agents_register_max_per_day: int
    tx_outbox_enabled: bool
    marketing_fee_bps: int


@lru_cache
def get_settings() -> Settings:
    app_version = os.getenv("APP_VERSION", "0.0.0")
    env = os.getenv("ENV", "development")
    cors_origins_value = os.getenv("CORS_ORIGINS", "")
    cors_origins = _split_origins(cors_origins_value)
    database_url_value = os.getenv("DATABASE_URL", "").strip()
    database_url = _normalize_database_url(database_url_value) if database_url_value else None
    oracle_hmac_secret_value = os.getenv("ORACLE_HMAC_SECRET", "").strip()
    oracle_hmac_secret = oracle_hmac_secret_value if oracle_hmac_secret_value else None

    base_sepolia_rpc_url_value = os.getenv("BASE_SEPOLIA_RPC_URL", "").strip()
    base_sepolia_rpc_url = base_sepolia_rpc_url_value if base_sepolia_rpc_url_value else None
    usdc_address_value = os.getenv("USDC_ADDRESS", "").strip()
    usdc_address = usdc_address_value if usdc_address_value else None
    distributor_address_value = os.getenv("DIVIDEND_DISTRIBUTOR_CONTRACT_ADDRESS", "").strip()
    dividend_distributor_contract_address = (
        distributor_address_value if distributor_address_value else None
    )
    funding_pool_address_value = os.getenv("FUNDING_POOL_CONTRACT_ADDRESS", "").strip()
    funding_pool_contract_address = funding_pool_address_value if funding_pool_address_value else None
    marketing_treasury_address_value = os.getenv("MARKETING_TREASURY_ADDRESS", "").strip()
    marketing_treasury_address = marketing_treasury_address_value if marketing_treasury_address_value else None
    safe_owner_address_value = os.getenv("SAFE_OWNER_ADDRESS", "").strip()
    safe_owner_address = safe_owner_address_value if safe_owner_address_value else None
    oracle_signer_private_key_value = os.getenv("ORACLE_SIGNER_PRIVATE_KEY", "").strip()
    oracle_signer_private_key = (
        oracle_signer_private_key_value if oracle_signer_private_key_value else None
    )
    contracts_dir = os.getenv("CONTRACTS_DIR", "/app/contracts").strip() or "/app/contracts"
    oracle_request_ttl_seconds = int(os.getenv("ORACLE_REQUEST_TTL_SECONDS", "300"))
    oracle_clock_skew_seconds = int(os.getenv("ORACLE_CLOCK_SKEW_SECONDS", "5"))
    oracle_accept_legacy_signatures = os.getenv("ORACLE_ACCEPT_LEGACY_SIGNATURES", "false").strip().lower() in {"1", "true", "yes", "on"}
    governance_quorum_min_votes = int(os.getenv("GOVERNANCE_QUORUM_MIN_VOTES", "1"))
    governance_approval_bps = int(os.getenv("GOVERNANCE_APPROVAL_BPS", "5000"))
    governance_discussion_hours = int(os.getenv("GOVERNANCE_DISCUSSION_HOURS", "24"))
    governance_voting_hours = int(os.getenv("GOVERNANCE_VOTING_HOURS", "24"))
    governance_discussion_minutes = _optional_int_env("GOVERNANCE_DISCUSSION_MINUTES")
    governance_voting_minutes = _optional_int_env("GOVERNANCE_VOTING_MINUTES")
    project_capital_reconciliation_max_age_seconds = int(
        os.getenv("PROJECT_CAPITAL_RECONCILIATION_MAX_AGE_SECONDS", "3600")
    )
    project_revenue_reconciliation_max_age_seconds = int(
        os.getenv("PROJECT_REVENUE_RECONCILIATION_MAX_AGE_SECONDS", "3600")
    )
    tx_outbox_lock_ttl_seconds = int(os.getenv("TX_OUTBOX_LOCK_TTL_SECONDS", "300"))
    tx_outbox_pending_max_age_seconds = int(os.getenv("TX_OUTBOX_PENDING_MAX_AGE_SECONDS", "900"))
    tx_outbox_processing_max_age_seconds = int(os.getenv("TX_OUTBOX_PROCESSING_MAX_AGE_SECONDS", "900"))
    git_outbox_pending_max_age_seconds = int(os.getenv("GIT_OUTBOX_PENDING_MAX_AGE_SECONDS", "1800"))
    git_outbox_processing_max_age_seconds = int(os.getenv("GIT_OUTBOX_PROCESSING_MAX_AGE_SECONDS", "1800"))
    indexer_cursor_max_age_seconds = int(os.getenv("INDEXER_CURSOR_MAX_AGE_SECONDS", "300"))
    discussions_create_thread_max_per_minute = int(
        os.getenv("DISCUSSIONS_CREATE_THREAD_MAX_PER_MINUTE", "5")
    )
    discussions_create_post_max_per_minute = int(
        os.getenv("DISCUSSIONS_CREATE_POST_MAX_PER_MINUTE", "20")
    )
    discussions_create_thread_max_per_day = int(
        os.getenv("DISCUSSIONS_CREATE_THREAD_MAX_PER_DAY", "50")
    )
    discussions_create_post_max_per_day = int(
        os.getenv("DISCUSSIONS_CREATE_POST_MAX_PER_DAY", "400")
    )
    agents_register_max_per_minute = int(os.getenv("AGENTS_REGISTER_MAX_PER_MINUTE", "10"))
    agents_register_max_per_day = int(os.getenv("AGENTS_REGISTER_MAX_PER_DAY", "200"))
    tx_outbox_enabled = os.getenv("TX_OUTBOX_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}
    marketing_fee_bps = int(os.getenv("MARKETING_FEE_BPS", "100"))

    return Settings(
        app_version=app_version,
        env=env,
        cors_origins=cors_origins,
        database_url=database_url,
        oracle_hmac_secret=oracle_hmac_secret,
        base_sepolia_rpc_url=base_sepolia_rpc_url,
        usdc_address=usdc_address,
        dividend_distributor_contract_address=dividend_distributor_contract_address,
        funding_pool_contract_address=funding_pool_contract_address,
        marketing_treasury_address=marketing_treasury_address,
        safe_owner_address=safe_owner_address,
        oracle_signer_private_key=oracle_signer_private_key,
        contracts_dir=contracts_dir,
        oracle_request_ttl_seconds=oracle_request_ttl_seconds,
        oracle_clock_skew_seconds=oracle_clock_skew_seconds,
        oracle_accept_legacy_signatures=oracle_accept_legacy_signatures,
        governance_quorum_min_votes=governance_quorum_min_votes,
        governance_approval_bps=governance_approval_bps,
        governance_discussion_hours=governance_discussion_hours,
        governance_voting_hours=governance_voting_hours,
        governance_discussion_minutes=governance_discussion_minutes,
        governance_voting_minutes=governance_voting_minutes,
        project_capital_reconciliation_max_age_seconds=project_capital_reconciliation_max_age_seconds,
        project_revenue_reconciliation_max_age_seconds=project_revenue_reconciliation_max_age_seconds,
        tx_outbox_lock_ttl_seconds=tx_outbox_lock_ttl_seconds,
        tx_outbox_pending_max_age_seconds=tx_outbox_pending_max_age_seconds,
        tx_outbox_processing_max_age_seconds=tx_outbox_processing_max_age_seconds,
        git_outbox_pending_max_age_seconds=git_outbox_pending_max_age_seconds,
        git_outbox_processing_max_age_seconds=git_outbox_processing_max_age_seconds,
        indexer_cursor_max_age_seconds=indexer_cursor_max_age_seconds,
        discussions_create_thread_max_per_minute=discussions_create_thread_max_per_minute,
        discussions_create_post_max_per_minute=discussions_create_post_max_per_minute,
        discussions_create_thread_max_per_day=discussions_create_thread_max_per_day,
        discussions_create_post_max_per_day=discussions_create_post_max_per_day,
        agents_register_max_per_minute=agents_register_max_per_minute,
        agents_register_max_per_day=agents_register_max_per_day,
        tx_outbox_enabled=tx_outbox_enabled,
        marketing_fee_bps=marketing_fee_bps,
    )
