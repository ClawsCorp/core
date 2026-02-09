from __future__ import annotations

import hashlib
import hmac
import secrets
from typing import Final

PBKDF2_ALGORITHM: Final[str] = "sha256"
PBKDF2_ITERATIONS: Final[int] = 200_000
PBKDF2_SALT_BYTES: Final[int] = 16


def generate_api_key() -> str:
    return secrets.token_urlsafe(32)


def api_key_last4(api_key: str) -> str:
    return api_key[-4:]


def hash_api_key(api_key: str) -> str:
    salt = secrets.token_bytes(PBKDF2_SALT_BYTES)
    derived = hashlib.pbkdf2_hmac(
        PBKDF2_ALGORITHM,
        api_key.encode("utf-8"),
        salt,
        PBKDF2_ITERATIONS,
    )
    return (
        f"pbkdf2_{PBKDF2_ALGORITHM}"
        f"${PBKDF2_ITERATIONS}"
        f"${salt.hex()}"
        f"${derived.hex()}"
    )


def verify_api_key(api_key: str, stored_hash: str) -> bool:
    try:
        algorithm, iterations, salt_hex, derived_hex = stored_hash.split("$")
        if algorithm != f"pbkdf2_{PBKDF2_ALGORITHM}":
            return False
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(derived_hex)
        derived = hashlib.pbkdf2_hmac(
            PBKDF2_ALGORITHM,
            api_key.encode("utf-8"),
            salt,
            int(iterations),
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(derived, expected)


def hash_body(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def verify_hmac_v1(secret: str, timestamp: str, body_hash: str, signature: str) -> bool:
    message = f"{timestamp}.{body_hash}".encode("utf-8")
    computed = hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()
    return hmac.compare_digest(computed, signature)
