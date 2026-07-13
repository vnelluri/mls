"""Shared Snowflake connection factory for the real executors
(data_pipeline unloads and load_to_snowflake loads).

The platform connects as a single SERVICE ACCOUNT. Key-pair auth is the
standard: SNOWFLAKE_PRIVATE_KEY holds PEM content (arriving as an SSM
SecureString -> env var in AWS); SNOWFLAKE_PASSWORD is the non-prod fallback.
"""
from typing import Optional

from app.config import settings


def _private_key_der() -> bytes:
    """Key-pair auth: the PEM arrives via SSM SecureString -> env var; the
    connector wants DER."""
    from cryptography.hazmat.primitives import serialization

    passphrase = settings.SNOWFLAKE_PRIVATE_KEY_PASSPHRASE or None
    key = serialization.load_pem_private_key(
        settings.SNOWFLAKE_PRIVATE_KEY.encode("utf-8"),
        password=passphrase.encode("utf-8") if passphrase else None,
    )
    return key.private_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )


def connect(warehouse: Optional[str] = None):
    import snowflake.connector

    kwargs = {
        "account": settings.SNOWFLAKE_ACCOUNT,
        "user": settings.SNOWFLAKE_USER,
        # The platform polls/cancels queries it started; nothing here needs
        # an interactive session.
        "client_session_keep_alive": False,
        # Bounds a hung connect/poll so it can't stall the shared refresh
        # loop (or a synchronous GET /jobs/{id} request) indefinitely.
        "login_timeout": settings.SNOWFLAKE_LOGIN_TIMEOUT_SECONDS,
        "network_timeout": settings.SNOWFLAKE_NETWORK_TIMEOUT_SECONDS,
    }
    if settings.SNOWFLAKE_ROLE:
        kwargs["role"] = settings.SNOWFLAKE_ROLE
    if warehouse:
        kwargs["warehouse"] = warehouse
    if settings.SNOWFLAKE_PRIVATE_KEY:
        kwargs["private_key"] = _private_key_der()
    else:
        kwargs["password"] = settings.SNOWFLAKE_PASSWORD
    return snowflake.connector.connect(**kwargs)
