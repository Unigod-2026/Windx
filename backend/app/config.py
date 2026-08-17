from functools import lru_cache
from pathlib import Path
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


# Repo-root ``.env`` (one level above this file). pydantic-settings
# loads ``env_file`` relative to CWD by default; pointing it at an
# absolute path keeps behaviour stable whether the process is started
# from the repo root, ``backend/``, or a Docker container.
_REPO_ROOT_ENV = str(Path(__file__).resolve().parents[2] / ".env")


class Settings(BaseSettings):
    """Process configuration loaded from environment / ``.env``.

    No real values are hardcoded here — every default below is a safe
    fallback (``""`` / ``0`` / ``False``) used only when the matching
    environment variable is absent. Production / dev values live in
    ``.env`` at the repo root. Two fields are strictly required because
    the app cannot start without them: ``database_url`` and ``jwt_secret``.
    """

    model_config = SettingsConfigDict(env_file=_REPO_ROOT_ENV, extra="ignore")

    # ---- Process / infra --------------------------------------------------
    app_port: int = 0
    tz: str = ""
    database_url: str

    # ---- Molizhishu remote (legacy; LLM backend now does the work) -------
    molizhishu_token: str = ""
    molizhishu_base_url: str = ""
    molizhishu_city_url: str = ""
    molizhishu_callback_url: str = ""
    molizhishu_timeout_seconds: int = 0
    molizhishu_sync_enabled: bool = False
    molizhishu_sync_interval_seconds: int = 0
    molizhishu_sync_limit: int = 0
    molizhishu_allow_api_key_update: bool = False

    # ---- LLM (Anthropic-compatible) backend -------------------------------
    llm_mode: str = ""
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = ""
    llm_timeout_seconds: int = 0
    llm_max_tool_rounds: int = 0
    llm_web_fetch_max_bytes: int = 0
    llm_max_concurrency: int = 0

    # ---- Logos / uploads --------------------------------------------------
    logo_storage_dir: str = Field(default="")
    logo_max_bytes: int = 0

    # ---- Logging ----------------------------------------------------------
    log_dir: str = ""
    log_level: str = ""

    # ---- JWT --------------------------------------------------------------
    jwt_secret: str = Field(..., min_length=1)
    jwt_algorithm: str = ""
    jwt_expire_days: int = 0


@lru_cache
def get_settings() -> Settings:
    return Settings()