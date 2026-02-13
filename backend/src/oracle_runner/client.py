from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from dataclasses import dataclass
from typing import Any
from urllib import error, request
from uuid import uuid4


class OracleRunnerError(Exception):
    """Raised for sanitized runner errors."""


@dataclass(frozen=True)
class OracleClientConfig:
    base_url: str
    hmac_secret: str
    timeout_seconds: float = 30.0
    request_ttl_seconds: int | None = None
    clock_skew_seconds: int | None = None


@dataclass(frozen=True)
class OracleHttpResponse:
    status_code: int
    data: dict[str, Any]


def load_config_from_env() -> OracleClientConfig:
    base_url = os.getenv("ORACLE_BASE_URL", "").strip()
    hmac_secret = os.getenv("ORACLE_HMAC_SECRET", "").strip()
    if not base_url:
        raise OracleRunnerError("ORACLE_BASE_URL is required.")
    if not hmac_secret:
        raise OracleRunnerError("ORACLE_HMAC_SECRET is required.")

    ttl = _optional_int_env("ORACLE_REQUEST_TTL_SECONDS")
    skew = _optional_int_env("ORACLE_CLOCK_SKEW_SECONDS")
    return OracleClientConfig(
        base_url=base_url.rstrip("/"),
        hmac_secret=hmac_secret,
        request_ttl_seconds=ttl,
        clock_skew_seconds=skew,
    )


def _optional_int_env(name: str) -> int | None:
    value = os.getenv(name, "").strip()
    if not value:
        return None
    try:
        return int(value)
    except ValueError as exc:
        raise OracleRunnerError(f"{name} must be an integer.") from exc


class OracleClient:
    def __init__(self, config: OracleClientConfig):
        self._config = config

    def post(
        self,
        path: str,
        *,
        body_bytes: bytes,
        idempotency_key: str | None = None,
    ) -> OracleHttpResponse:
        method = "POST"
        timestamp = str(int(time.time()))
        request_id = str(uuid4())
        body_hash = hashlib.sha256(body_bytes).hexdigest()
        payload = f"{timestamp}.{request_id}.{method}.{path}.{body_hash}"
        signature = hmac.new(
            self._config.hmac_secret.encode("utf-8"),
            payload.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        headers = {
            "X-Request-Timestamp": timestamp,
            "X-Request-Id": request_id,
            "X-Signature": signature,
            "Content-Type": "application/json",
        }
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key

        req = request.Request(
            url=f"{self._config.base_url}{path}",
            data=body_bytes,
            headers=headers,
            method=method,
        )

        try:
            with request.urlopen(req, timeout=self._config.timeout_seconds) as resp:
                return OracleHttpResponse(status_code=resp.status, data=_parse_json_response(resp.read()))
        except error.HTTPError as exc:
            payload_data = _parse_json_response(exc.read())
            raise OracleRunnerError(
                f"HTTP {exc.code} calling {path}: {payload_data.get('detail', 'request failed')}"
            ) from exc
        except error.URLError as exc:
            raise OracleRunnerError(f"Network error calling {path}: {exc.reason}") from exc


def to_json_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def _parse_json_response(raw: bytes) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise OracleRunnerError("Server returned non-JSON response.") from exc
    if not isinstance(parsed, dict):
        raise OracleRunnerError("Server returned unexpected JSON payload.")
    return parsed
