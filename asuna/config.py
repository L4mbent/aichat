from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    # DeepSeek API
    DEEPSEEK_API_KEY: str
    DEEPSEEK_BASE_URL: str = "https://api.deepseek.com/v1"
    DEEPSEEK_MODEL: str = "deepseek-chat"

    # iLink WeChat ClawBot
    ILINK_BASE_URL: str = "https://ilinkai.weixin.qq.com"
    ILINK_APP_ID: str = "bot"
    ILINK_CLIENT_VERSION: int = 131073  # 0x00020001 = v2.0.1
    ILINK_LONG_POLL_TIMEOUT: int = 35

    # Server
    HOST: str = "0.0.0.0"
    PORT: int = 8080

    # Database
    DATABASE_URL: str = "sqlite+aiosqlite:///data/asuna.db"

    # Rate limiting
    RATE_LIMIT_PER_MINUTE: int = 10
    RATE_LIMIT_PER_HOUR: int = 100

    # Conversation
    MAX_HISTORY_TURNS: int = 30
    SESSION_TIMEOUT_MINUTES: int = 30

    # Logging
    LOG_LEVEL: str = "INFO"


settings = Settings()
