import utils.credentials as credentials


def test_load_credentials_prefers_config(monkeypatch):
    monkeypatch.setenv(credentials.DEFAULT_API_KEY_ENV, "env-key")
    monkeypatch.setenv(credentials.DEFAULT_API_SECRET_ENV, "env-secret")
    monkeypatch.setattr(
        credentials.keyring,
        "get_password",
        lambda service, username: f"ring-{username}",
    )

    config = {"api_key": "config-key", "api_secret": "config-secret"}
    resolved = credentials.load_api_credentials(
        credentials.DEFAULT_SERVICE_NAME, config
    )

    assert resolved.api_key == "config-key"
    assert resolved.api_secret == "config-secret"


def test_load_credentials_uses_env_when_config_missing(monkeypatch):
    monkeypatch.setenv(credentials.DEFAULT_API_KEY_ENV, "env-key")
    monkeypatch.setenv(credentials.DEFAULT_API_SECRET_ENV, "env-secret")
    monkeypatch.setattr(
        credentials.keyring,
        "get_password",
        lambda service, username: f"ring-{username}",
    )

    resolved = credentials.load_api_credentials(credentials.DEFAULT_SERVICE_NAME, {})

    assert resolved.api_key == "env-key"
    assert resolved.api_secret == "env-secret"


def test_load_credentials_uses_keyring_when_env_missing(monkeypatch):
    monkeypatch.delenv(credentials.DEFAULT_API_KEY_ENV, raising=False)
    monkeypatch.delenv(credentials.DEFAULT_API_SECRET_ENV, raising=False)
    monkeypatch.setattr(
        credentials.keyring,
        "get_password",
        lambda service, username: f"ring-{username}",
    )

    resolved = credentials.load_api_credentials(credentials.DEFAULT_SERVICE_NAME, {})

    assert resolved.api_key == "ring-api_key"
    assert resolved.api_secret == "ring-api_secret"


def test_load_credentials_resolves_env_placeholders(monkeypatch):
    monkeypatch.setenv("CUSTOM_API_KEY", "env-key")
    monkeypatch.setenv("CUSTOM_API_SECRET", "env-secret")
    monkeypatch.setattr(
        credentials.keyring,
        "get_password",
        lambda service, username: None,
    )

    config = {"api_key": "${CUSTOM_API_KEY}", "api_secret": "${CUSTOM_API_SECRET}"}
    resolved = credentials.load_api_credentials(
        credentials.DEFAULT_SERVICE_NAME, config
    )

    assert resolved.api_key == "env-key"
    assert resolved.api_secret == "env-secret"


def test_store_credentials_writes_keyring(monkeypatch):
    calls = []

    def fake_set_password(service, username, password):
        calls.append((service, username, password))

    monkeypatch.setattr(credentials.keyring, "set_password", fake_set_password)

    credentials.store_api_credentials("service", "key", "secret")

    assert calls == [
        ("service", "api_key", "key"),
        ("service", "api_secret", "secret"),
    ]
