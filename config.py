from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    bot_token: str = ""
    admin_id: int = 7425677220
    bot_username: str = "vidownly_bot"

    db_path: str = "vidownly.db"
    default_language: str = "en"

    # Free plan
    free_downloads_per_day: int = 3
    free_download_reset_hours: int = 24

    # Prices in Telegram Stars
    price_sd: int = 5
    price_hd: int = 10
    price_fullhd: int = 20
    price_audio: int = 3
    price_subtitle: int = 5
    price_weekly: int = 49
    price_monthly: int = 149

    # General
    support_username: str = "@vidownly_support"
    app_name: str = "Vidownly"


settings = Settings()
