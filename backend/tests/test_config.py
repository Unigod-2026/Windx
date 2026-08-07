"""Tests for the Settings class loaded via pydantic-settings.

Each test clears the lru_cache on `get_settings` so a fresh Settings() is
constructed from the current process environment.
"""

from app.config import Settings, get_settings


def setup_function(_fn: object) -> None:
    get_settings.cache_clear()


def teardown_function(_fn: object) -> None:
    get_settings.cache_clear()


def test_default_app_port() -> None:
    settings = Settings()
    assert settings.app_port == 18083


def test_default_tz() -> None:
    settings = Settings()
    assert settings.tz == "Asia/Shanghai"


def test_default_molizhishu_base_url() -> None:
    settings = Settings()
    assert (
        settings.molizhishu_base_url
        == "https://business-api.molizhishu.com/api/business/monitor"
    )


def test_default_molizhishu_timeout_seconds() -> None:
    settings = Settings()
    assert settings.molizhishu_timeout_seconds == 30


def test_logo_max_bytes_default() -> None:
    settings = Settings()
    assert settings.logo_max_bytes == 2 * 1024 * 1024


def test_get_settings_is_cached() -> None:
    """Calling get_settings twice returns the same instance."""
    s1 = get_settings()
    s2 = get_settings()
    assert s1 is s2
