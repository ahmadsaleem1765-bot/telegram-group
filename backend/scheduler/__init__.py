"""
Scheduler Module

Handles scheduled automation runs.
"""

import asyncio
import logging
from typing import Optional, Callable, Dict, Any
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum

logger = logging.getLogger(__name__)


class ScheduleType(Enum):
    """Type of schedule"""
    NONE = "none"
    ONCE = "once"
    DAILY = "daily"
    INTERVAL = "interval"


@dataclass
class Schedule:
    """Defines a schedule for automation"""
    schedule_type: ScheduleType = ScheduleType.NONE
    start_time: Optional[datetime] = None
    interval_hours: int = 24

    def to_dict(self) -> Dict[str, Any]:
        return {
            'schedule_type': self.schedule_type.value,
            'start_time': self.start_time.isoformat() if self.start_time else None,
            'interval_hours': self.interval_hours
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Schedule':
        st = data.get('start_time')
        if st:
            st = datetime.fromisoformat(st)

        return cls(
            schedule_type=ScheduleType(data.get('schedule_type', 'none')),
            start_time=st,
            interval_hours=data.get('interval_hours', 24)
        )


@dataclass
class SchedulerState:
    """Current state of the scheduler"""
    is_running: bool = False
    is_paused: bool = False
    last_run: Optional[datetime] = None
    next_run: Optional[datetime] = None
    total_runs: int = 0
    failed_runs: int = 0


class Scheduler:
    """Manages scheduled automation runs"""

    def __init__(self):
        self._schedule: Optional[Schedule] = None
        self._state = SchedulerState()
        self._task: Optional[asyncio.Task] = None
        self._automation_callback: Optional[Callable] = None
        self._should_stop = False

    @property
    def schedule(self) -> Optional[Schedule]:
        return self._schedule

    @property
    def state(self) -> SchedulerState:
        return self._state

    @property
    def is_active(self) -> bool:
        return self._schedule is not None and self._schedule.schedule_type != ScheduleType.NONE

    def set_schedule(self, schedule: Schedule):
        """Set the schedule"""
        self._schedule = schedule
        self._calculate_next_run()
        logger.info(f"Schedule set: {schedule.schedule_type.value}")

    def set_automation_callback(self, callback: Callable):
        """Set the callback to execute for automation"""
        self._automation_callback = callback

    def _calculate_next_run(self):
        """Calculate the next run time based on schedule"""
        if not self._schedule:
            return

        now = datetime.now(timezone.utc)

        if self._schedule.schedule_type == ScheduleType.ONCE:
            self._state.next_run = self._schedule.start_time

        elif self._schedule.schedule_type == ScheduleType.DAILY:
            start_hours = self._schedule.start_time.hour if self._schedule.start_time else now.hour
            start_minutes = self._schedule.start_time.minute if self._schedule.start_time else now.minute

            if self._schedule.start_time and self._schedule.start_time > now:
                self._state.next_run = self._schedule.start_time
            else:
                # Schedule for next day at the same time
                next_time = now.replace(
                    hour=start_hours,
                    minute=start_minutes,
                    second=0,
                    microsecond=0
                )
                if next_time <= now:
                    next_time += timedelta(days=1)
                self._state.next_run = next_time

        elif self._schedule.schedule_type == ScheduleType.INTERVAL:
            self._state.next_run = now + timedelta(hours=self._schedule.interval_hours)

    async def start(self):
        """Start the scheduler"""
        if not self._schedule or self._schedule.schedule_type == ScheduleType.NONE:
            logger.warning("No schedule set, cannot start scheduler")
            return

        if not self._automation_callback:
            logger.error("No automation callback set")
            return

        self._should_stop = False
        self._state.is_running = True

        logger.info(f"Scheduler started. Next run: {self._state.next_run}")

        while not self._should_stop:
            if self._state.is_paused:
                await asyncio.sleep(1)
                continue

            # Check if it's time to run
            if self._state.next_run and datetime.now(timezone.utc) >= self._state.next_run:
                await self._run_automation()
                self._calculate_next_run()

            # Wait a bit before checking again
            await asyncio.sleep(10)

        self._state.is_running = False
        logger.info("Scheduler stopped")

    async def _run_automation(self):
        """Execute the automation callback"""
        try:
            logger.info("Running scheduled automation...")
            self._state.last_run = datetime.now(timezone.utc)

            if self._automation_callback:
                await self._automation_callback()

            self._state.total_runs += 1
            logger.info(f"Scheduled automation completed. Total runs: {self._state.total_runs}")

        except Exception as e:
            self._state.failed_runs += 1
            logger.error(f"Scheduled automation failed: {e}")

    def pause(self):
        """Pause the scheduler"""
        self._state.is_paused = True
        logger.info("Scheduler paused")

    def resume(self):
        """Resume the scheduler"""
        self._state.is_paused = False
        logger.info("Scheduler resumed")

    def stop(self):
        """Stop the scheduler"""
        self._should_stop = True
        self._state.is_running = False
        logger.info("Scheduler stop requested")

    def clear_schedule(self):
        """Clear the current schedule"""
        self._schedule = None
        self._state = SchedulerState()
        logger.info("Schedule cleared")

    def get_status(self) -> Dict[str, Any]:
        """Get scheduler status"""
        return {
            'is_active': self.is_active,
            'is_running': self._state.is_running,
            'is_paused': self._state.is_paused,
            'schedule': self._schedule.to_dict() if self._schedule else None,
            'last_run': self._state.last_run.isoformat() if self._state.last_run else None,
            'next_run': self._state.next_run.isoformat() if self._state.next_run else None,
            'total_runs': self._state.total_runs,
            'failed_runs': self._state.failed_runs
        }


# Global scheduler instance
scheduler = Scheduler()

__all__ = ['Schedule', 'ScheduleType', 'SchedulerState', 'Scheduler', 'scheduler']
