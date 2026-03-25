import os
from dataclasses import dataclass
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


@dataclass
class Config:
    """Application configuration"""

    # Telegram API credentials (should be set via environment variables)
    api_id: str = os.getenv("API_ID", "")
    api_hash: str = os.getenv("API_HASH", "")
    session_string: str = os.getenv("SESSION_STRING", "")

    # Flask settings
    host: str = os.getenv("HOST", "0.0.0.0")
    port: int = int(os.getenv("PORT", "5000"))
    debug: bool = os.getenv("DEBUG", "false").lower() == "true"

    # Message automation settings
    default_delay_min: int = int(os.getenv("DEFAULT_DELAY_MIN", "10"))
    default_delay_max: int = int(os.getenv("DEFAULT_DELAY_MAX", "30"))
    max_messages_per_run: int = int(os.getenv("MAX_MESSAGES_PER_RUN", "50"))

    # Data paths
    data_dir: str = os.getenv("DATA_DIR", "data")
    logs_dir: str = os.getenv("LOGS_DIR", "logs")

    # Session file path
    session_file: str = os.path.join(data_dir, "session.session")

    # Ad scheduling settings
    content_dir: str = os.getenv("CONTENT_DIR", "content")
    schedule_time: str = os.getenv("SCHEDULE_TIME", "09:00")
    schedule_timezone: str = os.getenv("SCHEDULE_TIMEZONE", "UTC")
    delivery_ledger_path: str = os.getenv(
        "DELIVERY_LEDGER_PATH",
        os.path.join(os.getenv("DATA_DIR", "data"), "delivery_ledger.json"),
    )
    delivery_max_retries: int = int(os.getenv("DELIVERY_MAX_RETRIES", "3"))
    delivery_inter_delay: float = float(os.getenv("DELIVERY_INTER_DELAY", "5.0"))

    @property
    def schedule_hour(self) -> int:
        """Parse hour from SCHEDULE_TIME (HH:MM format)."""
        return int(self.schedule_time.split(":")[0])

    @property
    def schedule_minute(self) -> int:
        """Parse minute from SCHEDULE_TIME (HH:MM format)."""
        return int(self.schedule_time.split(":")[1])

    @property
    def is_configured(self) -> bool:
        """Check if required Telegram credentials are set"""
        return bool(self.api_id and self.api_hash)

    @property
    def has_session(self) -> bool:
        """Check if session string is available"""
        return bool(self.session_string)


# Global config instance
config = Config()
