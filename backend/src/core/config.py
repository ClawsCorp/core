from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import os


def _split_origins(value: str) -> list[str]:
    return [origin.strip() for origin in value.split(",") if origin.strip()]


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


@lru_cache
def get_settings() -> Settings:
    app_version = os.getenv("APP_VERSION", "0.0.0")
    env = os.getenv("ENV", "development")
    cors_origins_value = os.getenv("CORS_ORIGINS", "")
    cors_origins = _split_origins(cors_origins_value)
    database_url_value = os.getenv("DATABASE_URL", "").strip()
    database_url = database_url_value if database_url_value else None
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

    return Settings(
        app_version=app_version,
        env=env,
        cors_origins=cors_origins,
        database_url=database_url,
        oracle_hmac_secret=oracle_hmac_secret,
        base_sepolia_rpc_url=base_sepolia_rpc_url,
        usdc_address=usdc_address,
        dividend_distributor_contract_address=dividend_distributor_contract_address,
    )
