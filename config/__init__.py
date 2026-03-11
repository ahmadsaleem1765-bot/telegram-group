import os
from dataclasses import dataclass
from typing import Optional


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
