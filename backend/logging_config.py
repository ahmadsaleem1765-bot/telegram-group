"""
Structured Logging Configuration

Configures JSON-formatted structured logging for the application.
Each log entry includes timestamp, level, module, and structured fields
for tracking ad delivery, channel operations, and errors.
"""

import logging
import os
import sys

from pythonjsonlogger import jsonlogger


class StructuredFormatter(jsonlogger.JsonFormatter):
    """Custom JSON formatter with standard fields."""

    def add_fields(
        self,
        log_record: dict,
        record: logging.LogRecord,
        message_dict: dict,
    ) -> None:
        super().add_fields(log_record, record, message_dict)
        log_record["timestamp"] = self.formatTime(record, self.datefmt)
        log_record["level"] = record.levelname
        log_record["module"] = record.module
        log_record["logger"] = record.name
        if record.exc_info and not log_record.get("exc_info"):
            log_record["exc_info"] = self.formatException(record.exc_info)


def setup_logging(
    logs_dir: str = "logs",
    level: int = logging.INFO,
    json_format: bool = True,
) -> None:
    """Configure application-wide structured logging.

    Args:
        logs_dir: Directory to write log files.
        level: Logging level.
        json_format: If True, use JSON format. Otherwise, use plain text.
    """
    os.makedirs(logs_dir, exist_ok=True)

    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # Clear existing handlers to prevent duplicates on reload
    root_logger.handlers.clear()

    if json_format:
        formatter = StructuredFormatter(
            fmt="%(timestamp)s %(level)s %(name)s %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S%z",
        )
    else:
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )

    # File handler - structured JSON
    file_handler = logging.FileHandler(
        os.path.join(logs_dir, "app.log"), encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(level)

    # Console handler - plain text for readability
    console_handler = logging.StreamHandler(sys.stdout)
    console_formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    console_handler.setFormatter(console_formatter)
    console_handler.setLevel(level)

    # Delivery-specific log file (JSON only)
    delivery_handler = logging.FileHandler(
        os.path.join(logs_dir, "delivery.log"), encoding="utf-8"
    )
    delivery_formatter = StructuredFormatter(
        fmt="%(timestamp)s %(level)s %(name)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S%z",
    )
    delivery_handler.setFormatter(delivery_formatter)
    delivery_handler.setLevel(level)
    delivery_handler.addFilter(
        logging.Filter("backend.channel_adapter")
    )

    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)

    # Add delivery handler to the specific logger
    delivery_logger = logging.getLogger("backend.channel_adapter")
    delivery_logger.addHandler(delivery_handler)

    # Also capture ad_scheduler delivery logs
    ad_logger = logging.getLogger("backend.ad_scheduler")
    ad_logger.addHandler(delivery_handler)

    logging.info("Structured logging initialized (json=%s)", json_format)
