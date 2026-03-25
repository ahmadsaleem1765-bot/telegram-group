"""
Ad Scheduler Module

APScheduler-based daily ad delivery with idempotency tracking.
Ensures ads are not re-sent to the same destination on the same day
even if the process restarts.
"""

import json
import os
import logging
from typing import Optional, List, Dict, Any, Callable
from dataclasses import dataclass, field
from datetime import date, datetime, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from backend.content_manager import ContentManager
from backend.channel_adapter import (
    DeliveryEngine,
    Destination,
    DeliveryResult,
    DeliveryStatus,
)

logger = logging.getLogger(__name__)


@dataclass
class DeliveryRecord:
    """Tracks a single delivery for idempotency."""

    content_id: str
    content_hash: str
    destination_id: str
    delivery_date: str  # ISO date YYYY-MM-DD
    status: str
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "content_id": self.content_id,
            "content_hash": self.content_hash,
            "destination_id": self.destination_id,
            "delivery_date": self.delivery_date,
            "status": self.status,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DeliveryRecord":
        return cls(
            content_id=data["content_id"],
            content_hash=data["content_hash"],
            destination_id=data["destination_id"],
            delivery_date=data["delivery_date"],
            status=data["status"],
            timestamp=data.get(
                "timestamp", datetime.now(timezone.utc).isoformat()
            ),
        )


class DeliveryLedger:
    """Persistent ledger for tracking daily deliveries.

    Prevents duplicate sends on restart by recording every delivery
    keyed by (content_hash, destination_id, date).
    """

    def __init__(self, ledger_path: str) -> None:
        self._path = ledger_path
        self._records: List[DeliveryRecord] = []
        self._load()

    def _load(self) -> None:
        try:
            if os.path.exists(self._path):
                with open(self._path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._records = [
                    DeliveryRecord.from_dict(r) for r in data.get("records", [])
                ]
                logger.info(
                    "Loaded %d delivery records from ledger",
                    len(self._records),
                )
        except Exception as e:
            logger.error("Failed to load delivery ledger: %s", e)
            self._records = []

    def _save(self) -> None:
        try:
            os.makedirs(os.path.dirname(self._path), exist_ok=True)
            tmp = self._path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(
                    {"records": [r.to_dict() for r in self._records]},
                    f,
                    indent=2,
                )
            if os.path.exists(self._path):
                os.remove(self._path)
            os.rename(tmp, self._path)
        except Exception as e:
            logger.error("Failed to save delivery ledger: %s", e)

    def was_delivered(
        self, content_hash: str, destination_id: str, delivery_date: date
    ) -> bool:
        """Check if content was already successfully delivered today."""
        date_str = delivery_date.isoformat()
        return any(
            r.content_hash == content_hash
            and r.destination_id == destination_id
            and r.delivery_date == date_str
            and r.status == DeliveryStatus.SUCCESS.value
            for r in self._records
        )

    def record_delivery(
        self,
        content_id: str,
        content_hash: str,
        destination_id: str,
        delivery_date: date,
        status: DeliveryStatus,
    ) -> None:
        """Record a delivery attempt."""
        self._records.append(
            DeliveryRecord(
                content_id=content_id,
                content_hash=content_hash,
                destination_id=destination_id,
                delivery_date=delivery_date.isoformat(),
                status=status.value,
            )
        )
        self._save()

    def get_records_for_date(self, target_date: date) -> List[DeliveryRecord]:
        """Get all delivery records for a given date."""
        date_str = target_date.isoformat()
        return [r for r in self._records if r.delivery_date == date_str]

    def prune_before(self, cutoff_date: date) -> int:
        """Remove records older than cutoff_date. Returns count removed."""
        cutoff_str = cutoff_date.isoformat()
        initial = len(self._records)
        self._records = [
            r for r in self._records if r.delivery_date >= cutoff_str
        ]
        removed = initial - len(self._records)
        if removed > 0:
            self._save()
            logger.info("Pruned %d old delivery records", removed)
        return removed


class AdScheduler:
    """Manages scheduled daily ad delivery.

    Integrates ContentManager, DeliveryEngine, and DeliveryLedger
    to deliver the day's ad to all destinations at a configured time.
    """

    def __init__(
        self,
        content_manager: ContentManager,
        delivery_engine: DeliveryEngine,
        ledger: DeliveryLedger,
        schedule_hour: int = 9,
        schedule_minute: int = 0,
        timezone_str: str = "UTC",
    ) -> None:
        self._content_manager = content_manager
        self._delivery_engine = delivery_engine
        self._ledger = ledger
        self._schedule_hour = schedule_hour
        self._schedule_minute = schedule_minute
        self._timezone_str = timezone_str
        self._destinations: List[Destination] = []
        self._scheduler: Optional[AsyncIOScheduler] = None
        self._is_running = False
        self._last_run: Optional[datetime] = None
        self._log_callback: Optional[Callable[[str], Any]] = None

    @property
    def is_running(self) -> bool:
        return self._is_running

    @property
    def last_run(self) -> Optional[datetime]:
        return self._last_run

    def set_destinations(self, destinations: List[Destination]) -> None:
        """Set the list of destinations to deliver to."""
        self._destinations = destinations
        logger.info(
            "Ad scheduler: %d destinations configured",
            len(destinations),
        )

    def set_log_callback(self, callback: Callable[[str], Any]) -> None:
        """Set a callback for log messages (e.g., app_state.add_log)."""
        self._log_callback = callback

    def _log(self, message: str) -> None:
        logger.info(message)
        if self._log_callback:
            self._log_callback(message)

    def update_schedule(
        self, hour: int, minute: int, timezone_str: str = "UTC"
    ) -> None:
        """Update the schedule time. Restarts if already running."""
        self._schedule_hour = hour
        self._schedule_minute = minute
        self._timezone_str = timezone_str
        if self._is_running:
            self.stop()
            self.start()

    def start(self) -> None:
        """Start the APScheduler with a daily cron trigger."""
        if self._is_running:
            logger.warning("Ad scheduler already running")
            return

        self._scheduler = AsyncIOScheduler()
        trigger = CronTrigger(
            hour=self._schedule_hour,
            minute=self._schedule_minute,
            timezone=self._timezone_str,
        )
        self._scheduler.add_job(
            self.run_daily_delivery,
            trigger=trigger,
            id="daily_ad_delivery",
            replace_existing=True,
        )
        self._scheduler.start()
        self._is_running = True
        self._log(
            f"Ad scheduler started: daily at "
            f"{self._schedule_hour:02d}:{self._schedule_minute:02d} "
            f"({self._timezone_str})"
        )

    def stop(self) -> None:
        """Stop the scheduler."""
        if self._scheduler:
            self._scheduler.shutdown(wait=False)
            self._scheduler = None
        self._is_running = False
        self._log("Ad scheduler stopped")

    async def run_daily_delivery(self) -> List[DeliveryResult]:
        """Execute the daily delivery cycle.

        1. Select today's ad from ContentManager
        2. For each destination, check idempotency ledger
        3. Deliver via DeliveryEngine (with retry)
        4. Record results in ledger
        """
        today = date.today()
        self._last_run = datetime.now(timezone.utc)

        ad = self._content_manager.get_ad_for_date(today)
        if not ad:
            self._log("No active ad content for today, skipping delivery")
            return []

        if not self._destinations:
            self._log("No destinations configured, skipping delivery")
            return []

        self._log(
            f"Starting daily ad delivery: '{ad.title}' to "
            f"{len(self._destinations)} destinations"
        )

        # Resolve media
        media_path = self._content_manager.resolve_media_path(ad)
        media_type = ad.media_type if media_path else None

        results: List[DeliveryResult] = []
        for dest in self._destinations:
            # Idempotency check
            if self._ledger.was_delivered(
                ad.content_hash, dest.id, today
            ):
                self._log(
                    f"Skipping {dest.name}: already delivered today"
                )
                results.append(
                    DeliveryResult(
                        destination_id=dest.id,
                        destination_name=dest.name,
                        destination_type=dest.type,
                        status=DeliveryStatus.SKIPPED,
                        content_id=ad.id,
                        error="Already delivered today",
                    )
                )
                continue

            result = await self._delivery_engine.deliver(
                destination=dest,
                content_id=ad.id,
                text=ad.message or None,
                media_path=media_path,
                media_type=media_type,
            )
            results.append(result)

            # Record in ledger
            self._ledger.record_delivery(
                content_id=ad.id,
                content_hash=ad.content_hash,
                destination_id=dest.id,
                delivery_date=today,
                status=DeliveryStatus(result.status.value),
            )

        success = sum(
            1 for r in results if r.status == DeliveryStatus.SUCCESS
        )
        skipped = sum(
            1 for r in results if r.status == DeliveryStatus.SKIPPED
        )
        failed = sum(
            1 for r in results if r.status == DeliveryStatus.FAILED
        )
        self._log(
            f"Daily delivery complete: {success} sent, "
            f"{skipped} skipped, {failed} failed"
        )
        return results

    def get_status(self) -> Dict[str, Any]:
        """Get scheduler status for API responses."""
        return {
            "is_running": self._is_running,
            "schedule_time": (
                f"{self._schedule_hour:02d}:{self._schedule_minute:02d}"
            ),
            "timezone": self._timezone_str,
            "last_run": (
                self._last_run.isoformat() if self._last_run else None
            ),
            "destinations_count": len(self._destinations),
        }


__all__ = [
    "AdScheduler",
    "DeliveryLedger",
    "DeliveryRecord",
]
