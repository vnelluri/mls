"""Auth building blocks that don't need a live token: prod-config fail-fast
and claim parsing."""
import pytest

from app.auth import entra
from app.config import settings


def test_prod_config_fail_fast_lists_missing_settings(monkeypatch):
    monkeypatch.setattr(settings, "ENTRA_JWKS_URL", "")
    monkeypatch.setattr(settings, "ENTRA_ISSUER", "")
    monkeypatch.setattr(settings, "ENTRA_AUDIENCE", "")
    monkeypatch.setattr(settings, "ENTRA_CLIENT_ID", "")
    with pytest.raises(RuntimeError) as exc:
        entra.validate_prod_config()
    message = str(exc.value)
    assert "ENTRA_JWKS_URL" in message
    assert "ENTRA_ISSUER" in message
    assert "ENTRA_AUDIENCE" in message


def test_prod_config_accepts_client_id_as_audience(monkeypatch):
    monkeypatch.setattr(settings, "ENTRA_JWKS_URL", "https://login/keys")
    monkeypatch.setattr(settings, "ENTRA_ISSUER", "https://login/issuer")
    monkeypatch.setattr(settings, "ENTRA_AUDIENCE", "")
    monkeypatch.setattr(settings, "ENTRA_CLIENT_ID", "client-123")
    entra.validate_prod_config()  # must not raise


def test_extract_group_ids_shapes():
    assert entra.extract_group_ids({"groups": ["a", "b"]}) == ["a", "b"]
    assert entra.extract_group_ids({"groups": "single"}) == ["single"]
    assert entra.extract_group_ids({}) == []
