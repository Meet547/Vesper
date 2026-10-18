import pytest
from fastapi import HTTPException, Request
from backend.app.config import Settings
from types import SimpleNamespace
from fastapi.security import HTTPAuthorizationCredentials

from backend.app import main


def test_cognito_access_token_must_match_issuer_token_use_and_app_client(monkeypatch):
    import jwt

    settings = Settings(_env_file=None)
    request = Request({"type": "http", "app": SimpleNamespace(state=SimpleNamespace(settings=settings))})
    for name, value in {
        "auth_mode": "cognito", "app_host": "127.0.0.1", "cognito_region": "ap-south-1",
        "cognito_user_pool_id": "pool", "cognito_app_client_id": "client",
        "cognito_domain": "example.auth.ap-south-1.amazoncognito.com",
        "cognito_callback_url": "http://127.0.0.1:8000/",
    }.items():
        monkeypatch.setattr(settings, name, value)

    class FakeJwks:
        def __init__(self, *_args, **_kwargs): pass
        def get_signing_key_from_jwt(self, _token): return type("Key", (), {"key": "key"})()

    main.cognito_jwks_client.cache_clear()
    monkeypatch.setattr(main, "ResilientCognitoJwksClient", FakeJwks)
    monkeypatch.setattr(jwt, "decode", lambda *_args, **_kwargs: {
        "iss": "https://cognito-idp.ap-south-1.amazonaws.com/pool",
        "token_use": "access", "client_id": "client", "sub": "user-123", "exp": 9999999999,
    })
    credential = HTTPAuthorizationCredentials(scheme="Bearer", credentials="signed-token")
    assert main.require_auth(request, credential) == "user-123"

    monkeypatch.setattr(jwt, "decode", lambda *_args, **_kwargs: {
        "iss": "https://cognito-idp.ap-south-1.amazonaws.com/pool",
        "token_use": "id", "client_id": "client", "exp": 9999999999,
    })
    with pytest.raises(HTTPException) as error:
        main.require_auth(request, credential)
    assert error.value.status_code == 401

    monkeypatch.setattr(jwt, "decode", lambda *_args, **_kwargs: {
        "iss": "https://cognito-idp.ap-south-1.amazonaws.com/pool",
        "token_use": "access", "client_id": "client", "exp": 9999999999,
    })
    with pytest.raises(HTTPException) as missing_subject:
        main.require_auth(request, credential)
    assert missing_subject.value.status_code == 401
    main.cognito_jwks_client.cache_clear()


def test_cognito_jwks_client_is_shared_per_issuer(monkeypatch):
    from backend.app import main

    class FakeJwks:
        created = 0

        def __init__(self, uri):
            type(self).created += 1
            self.uri = uri

    main.cognito_jwks_client.cache_clear()
    monkeypatch.setattr(main, "ResilientCognitoJwksClient", FakeJwks)
    first = main.cognito_jwks_client("https://issuer.example/pool")
    second = main.cognito_jwks_client("https://issuer.example/pool")
    assert first is second
    assert FakeJwks.created == 1
    assert first.uri == "https://issuer.example/pool/.well-known/jwks.json"
    main.cognito_jwks_client.cache_clear()


def test_jwks_connection_failure_is_temporary_service_error(monkeypatch):
    import jwt

    from backend.app import main

    settings = Settings(_env_file=None)
    request = Request({"type": "http", "app": SimpleNamespace(state=SimpleNamespace(settings=settings))})
    for name, value in {
        "auth_mode": "cognito", "app_host": "127.0.0.1", "cognito_region": "ap-south-1",
        "cognito_user_pool_id": "pool", "cognito_app_client_id": "client",
        "cognito_domain": "example.auth.ap-south-1.amazoncognito.com",
        "cognito_callback_url": "http://127.0.0.1:8000/",
    }.items():
        monkeypatch.setattr(settings, name, value)

    class OfflineJwks:
        def __init__(self, _uri): pass
        def get_signing_key_from_jwt(self, _token): raise jwt.PyJWKClientConnectionError("offline")

    main.cognito_jwks_client.cache_clear()
    monkeypatch.setattr(main, "ResilientCognitoJwksClient", OfflineJwks)
    credential = HTTPAuthorizationCredentials(scheme="Bearer", credentials="opaque-test-token")
    with pytest.raises(HTTPException) as error:
        main.require_auth(request, credential)
    assert error.value.status_code == 503
    assert "temporarily unavailable" in error.value.detail
    main.cognito_jwks_client.cache_clear()


def test_jwks_uses_bounded_stale_set_only_for_normal_lookup(monkeypatch):
    import time
    import jwt

    from backend.app import main

    client = main.ResilientCognitoJwksClient("https://issuer.example/pool/.well-known/jwks.json")
    client._last_good_jwks = {"keys": [{"kid": "cached"}]}
    client._last_good_at = time.monotonic()
    marker = object()

    def unavailable(_self, refresh=False):
        raise jwt.PyJWKClientConnectionError("offline")

    monkeypatch.setattr(jwt.PyJWKClient, "get_jwk_set", unavailable)
    monkeypatch.setattr(jwt.PyJWKSet, "from_dict", lambda _data: marker)
    assert client.get_jwk_set() is marker
    with pytest.raises(jwt.PyJWKClientConnectionError):
        client.get_jwk_set(refresh=True)


def test_jwks_does_not_use_cache_past_stale_grace(monkeypatch):
    import time
    import jwt

    from backend.app import main

    client = main.ResilientCognitoJwksClient("https://issuer.example/pool/.well-known/jwks.json")
    client._last_good_jwks = {"keys": [{"kid": "cached"}]}
    client._last_good_at = time.monotonic() - main.JWKS_STALE_GRACE_SECONDS - 1

    def unavailable(_self, refresh=False):
        raise jwt.PyJWKClientConnectionError("offline")

    monkeypatch.setattr(jwt.PyJWKClient, "get_jwk_set", unavailable)
    with pytest.raises(jwt.PyJWKClientConnectionError):
        client.get_jwk_set()


def test_required_auth_rejects_missing_credentials(monkeypatch):
    from backend.app import main

    settings = Settings(_env_file=None)
    request = Request({"type": "http", "app": SimpleNamespace(state=SimpleNamespace(settings=settings))})
    monkeypatch.setattr(settings, "app_host", "0.0.0.0")
    monkeypatch.setattr(settings, "auth_mode", "cognito")
    for name in (
        "cognito_region", "cognito_user_pool_id", "cognito_app_client_id",
        "cognito_domain", "cognito_callback_url",
    ):
        monkeypatch.setattr(settings, name, "")
    with pytest.raises(HTTPException) as error:
        main.require_auth(request, None)
    assert error.value.status_code == 503  # no Cognito config, fail closed
