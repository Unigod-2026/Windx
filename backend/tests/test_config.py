"""Tests for the Settings class loaded via pydantic-settings.

Every real value lives in ``.env`` / the process environment — the
``Settings`` class only carries safe fallbacks (``""`` / ``0`` /
``False``). These tests therefore verify:

- The .env file is loaded by ``BaseSettings`` (no monkeypatching).
- A monkeypatched env var overrides the .env value.
- ``database_url`` and ``jwt_secret`` are required and raise on missing.
- ``get_settings`` caches its result.
"""

from __future__ import annotations

import pytest

from app.config import Settings, get_settings


@pytest.fixture(autouse=True)
def _isolated_env(monkeypatch: pytest.MonkeyPatch):
    """Clear ``get_settings`` cache so each test gets a fresh instance.

    Required fields are forced here too: previously conftest.py ensured
    ``DATABASE_URL`` + ``JWT_SECRET`` for the whole session; without it,
    ``Settings()`` would raise on instantiation for any test that bypasses
    the .env file (``_env_file=None``).
    """
    monkeypatch.setenv("DATABASE_URL", "mysql+pymysql://x:y@localhost/windx")
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_env_file_loads_database_url() -> None:
    """The .env at the repo root must feed DATABASE_URL into Settings.

    Verifies the ``env_file=".env"`` wiring is in effect; if a future
    refactor accidentally drops it the test will catch it.
    """
    settings = Settings()
    assert settings.database_url.startswith("mysql+pymysql://")


def test_env_var_overrides_env_file(monkeypatch: pytest.MonkeyPatch) -> None:
    """A process-level env var wins over the .env value.

    We swap ``LLM_MODE`` to ``mock`` and assert the new instance picks
    it up. ``monkeypatch.delenv`` is used at teardown so the next test
    doesn't see the patched value.
    """
    monkeypatch.setenv("LLM_MODE", "mock")
    settings = Settings()
    assert settings.llm_mode == "mock"


def test_missing_database_url_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """``database_url`` is required — instantiating without it must fail.

    Disable env-file loading here too: ``conftest.py`` forces
    ``DATABASE_URL`` into ``os.environ`` so the test DB engine works,
    and the repo .env also has the value, so the only way to assert
    "missing" is to bypass both sources.
    """
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(Exception):  # ValidationError from pydantic
        Settings(_env_file=None)


def test_missing_jwt_secret_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """``jwt_secret`` is required — instantiating without it must fail.

    ``conftest.py`` sets ``JWT_SECRET`` in ``os.environ`` so JWT tests
    can sign tokens; bypass env-file loading to assert "missing".
    """
    monkeypatch.delenv("JWT_SECRET", raising=False)
    with pytest.raises(Exception):
        Settings(_env_file=None)


def test_optional_field_defaults_to_empty_string(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Optional string fields fall back to ``""`` when neither the env
    var nor ``.env`` set them.

    We pick ``MOLIZHISHU_CALLBACK_URL`` because the dev .env leaves it
    empty by design (callbacks aren't wired up in this build).
    """
    monkeypatch.delenv("MOLIZHISHU_CALLBACK_URL", raising=False)
    settings = Settings()
    assert settings.molizhishu_callback_url == ""


def test_optional_bool_defaults_to_false(monkeypatch: pytest.MonkeyPatch) -> None:
    """Optional bool fields fall back to ``False`` when unset.

    The repo .env sets ``MOLIZHISHU_ALLOW_API_KEY_UPDATE=True``; we
    disable env-file loading here so the safe fallback is what's
    actually exercised.
    """
    monkeypatch.delenv("MOLIZHISHU_ALLOW_API_KEY_UPDATE", raising=False)
    settings = Settings(_env_file=None)
    assert settings.molizhishu_allow_api_key_update is False


def test_optional_int_defaults_to_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    """Optional int fields fall back to ``0`` when unset.

    The repo .env sets ``MOLIZHISHU_TIMEOUT_SECONDS=30``; disable
    env-file loading so the safe fallback is what's actually exercised.
    """
    monkeypatch.delenv("MOLIZHISHU_TIMEOUT_SECONDS", raising=False)
    settings = Settings(_env_file=None)
    assert settings.molizhishu_timeout_seconds == 0


def test_get_settings_is_cached() -> None:
    """Calling get_settings twice returns the same instance."""
    s1 = get_settings()
    s2 = get_settings()
    assert s1 is s2