from functools import lru_cache
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_port: int = 18083
    tz: str = "Asia/Shanghai"
    database_url: str

    molizhishu_token: str = ""
    molizhishu_base_url: str = "https://business-api.molizhishu.com/api/business/monitor"
    molizhishu_city_url: str = "https://business-api.molizhishu.com/api/business/eip-edge/ports/city-info"
    molizhishu_callback_url: str = ""
    molizhishu_timeout_seconds: int = 30
    molizhishu_sync_enabled: bool = True
    molizhishu_sync_interval_seconds: int = 60
    molizhishu_sync_limit: int = 20
    molizhishu_allow_api_key_update: bool = True

    logo_storage_dir: str = Field(default="/data/logos")
    logo_max_bytes: int = 2 * 1024 * 1024

    jwt_secret: str = "CHANGE-ME-IN-PROD"
    jwt_algorithm: str = "HS256"
    jwt_expire_days: int = 7


@lru_cache
def get_settings() -> Settings:
    return Settings()
