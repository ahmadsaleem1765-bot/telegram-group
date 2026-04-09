"""
Message Sender Module

Handles automated message sending to Telegram groups with rate limiting.
"""

import asyncio
import random
import logging
from typing import List, Optional, Dict, Any, Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

from telethon.errors import FloodWaitError, MessageNotModifiedError
from telethon.tl.types import InputPeerChannel, InputPeerChat, PeerChannel, PeerChat

from backend.group_scanner import Group
from backend.telegram_client import client_manager

logger = logging.getLogger(__name__)


class SendStatus(Enum):
    """Message send status"""
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"
    RATE_LIMITED = "rate_limited"
    SKIPPED = "skipped"


@dataclass
class MessageResult:
    """Result of sending a message to a group"""
    group_id: int
    group_name: str
    status: SendStatus
    message: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            'group_id': self.group_id,
            'group_name': self.group_name,
            'status': self.status.value,
            'message': self.message,
            'timestamp': self.timestamp.isoformat(),
            'error': self.error
        }


@dataclass
class AutomationConfig:
    """Configuration for message automation"""
    message_template: str
    delay_min: int = 10  # seconds
    delay_max: int = 30  # seconds
    max_messages: int = 50
    stop_on_error: bool = False
    dry_run: bool = False  # If True, don't actually send messages

    def get_random_delay(self) -> float:
        """Get random delay between messages"""
        return random.uniform(self.delay_min, self.delay_max)

    def validate(self) -> bool:
        """Validate configuration"""
        if not self.message_template or not self.message_template.strip():
            return False
        if self.delay_min < 1 or self.delay_max < self.delay_min:
            return False
        if self.max_messages < 1:
            return False
        return True


class MessageSender:
    """Sends automated messages to Telegram groups"""

    def __init__(self):
        self._is_running = False
        self._is_paused = False
        self._should_stop = False
        self._results: List[MessageResult] = []
        self._sent_count = 0
        self._failed_count = 0
        self._total_groups = 0

    @property
    def is_running(self) -> bool:
        return self._is_running

    @property
    def is_paused(self) -> bool:
        return self._is_paused

    @property
    def results(self) -> List[MessageResult]:
        return self._results

    @property
    def sent_count(self) -> int:
        return self._sent_count

    @property
    def failed_count(self) -> int:
        return self._failed_count

    @property
    def progress(self) -> float:
        if not self._total_groups:
            return 0.0
        return len(self._results) / self._total_groups

    def pause(self):
        """Pause the sending process"""
        self._is_paused = True
        logger.info("Message sending paused")

    def resume(self):
        """Resume the sending process"""
        self._is_paused = False
        logger.info("Message sending resumed")

    def stop(self):
        """Stop the sending process"""
        self._should_stop = True
        logger.info("Message sending stopped")

    def reset(self):
        """Reset the sender state"""
        self._is_running = False
        self._is_paused = False
        self._should_stop = False
        self._results = []
        self._sent_count = 0
        self._failed_count = 0
        self._total_groups = 0

    async def send_messages(
        self,
        groups: List[Group],
        config: AutomationConfig,
        progress_callback: Optional[Callable[[int, int, MessageResult], None]] = None,
        log_callback: Optional[Callable[[str], None]] = None
    ) -> List[MessageResult]:
        """
        Send messages to a list of groups.

        Args:
            groups: List of groups to send messages to
            config: Automation configuration
            progress_callback: Callback for progress updates (current, total, result)
            log_callback: Callback for logging messages

        Returns:
            List of message results
        """
        if not client_manager.is_authenticated:
            raise RuntimeError("Telegram client not authenticated")

        if not config.validate():
            raise ValueError("Invalid automation configuration")

        self.reset()
        self._is_running = True

        try:
            # Limit groups to max_messages
            groups_to_send = groups[:config.max_messages]
            total = len(groups_to_send)
            self._total_groups = total

            log_callback = log_callback or logger.info

            log_callback(f"Starting message automation to {total} groups")

            for idx, group in enumerate(groups_to_send):
                # Check if should stop
                if self._should_stop:
                    log_callback("Message sending stopped by user")
                    break

                # Wait for random delay (except for first message)
                if idx > 0:
                    delay = config.get_random_delay()
                    log_callback(f"Waiting {delay:.1f} seconds before next message...")
                    await asyncio.sleep(delay)

                # Check if paused
                while self._is_paused and not self._should_stop:
                    await asyncio.sleep(1)

                if self._should_stop:
                    break

                # Prepare message with dynamic variables
                try:
                    message = self._prepare_message(config.message_template, group)
                except Exception as e:
                    logger.error(f"Error preparing message for group {group.name}: {e}")
                    res = MessageResult(
                        group_id=group.id,
                        group_name=group.name,
                        status=SendStatus.FAILED,
                        message="",
                        error=f"Template error: {e}"
                    )
                    self._results.append(res)
                    self._failed_count += 1
                    if progress_callback:
                        progress_callback(idx + 1, total, res)
                    continue

                # Send message (or simulate in dry run)
                result = await self._send_single_message(
                    group,
                    message,
                    dry_run=config.dry_run
                )

                self._results.append(result)

                if result.status == SendStatus.SENT:
                    self._sent_count += 1
                    log_callback(f"[{idx + 1}/{total}] Message sent to: {group.name}")
                elif result.status == SendStatus.FAILED:
                    self._failed_count += 1
                    log_callback(f"[{idx + 1}/{total}] Failed to send to: {group.name} - {result.error}")

                if progress_callback:
                    progress_callback(idx + 1, total, result)

            log_callback(
                f"Message automation complete. "
                f"Sent: {self._sent_count}, Failed: {self._failed_count}"
            )

            return self._results
        finally:
            self._is_running = False

    def _prepare_message(self, template: str, group: Group) -> str:
        """Prepare message by replacing dynamic variables"""
        message = template

        # Replace dynamic variables
        replacements = {
            '{group_name}': group.name,
            '{group_id}': str(group.id),
            '{last_message}': (
                group.last_message_time.strftime("%Y-%m-%d %H:%M")
                if group.last_message_time
                else "Unknown"
            )
        }

        for key, value in replacements.items():
            message = message.replace(key, value)

        return message

    async def _send_single_message(
        self,
        group: Group,
        message: str,
        dry_run: bool = False
    ) -> MessageResult:
        """Send a single message to a group"""

        try:
            if dry_run:
                # Simulate sending
                logger.info(f"[DRY RUN] Would send to {group.name}: {message[:50]}...")
                return MessageResult(
                    group_id=group.id,
                    group_name=group.name,
                    status=SendStatus.SENT,
                    message=message
                )

            # Resolve the entity for reliable delivery.
            # Priority: Telethon session cache (freshest access_hash from
            # the get_dialogs warm-up) → username → stored InputPeer → raw ID.
            entity = None

            # Strategy 1: get_input_entity from session cache (best — uses
            # the access_hash Telethon fetched during the get_dialogs warm-up).
            # We must pass PeerChannel/PeerChat instead of a bare int because
            # Telethon treats a raw int as a "marked" ID, but entity.id stores
            # the bare (unmarked) channel ID, causing cache misses.
            try:
                if group.entity_type == 'channel':
                    entity = await client_manager.client.get_input_entity(PeerChannel(group.id))
                elif group.entity_type == 'chat':
                    entity = await client_manager.client.get_input_entity(PeerChat(group.id))
                else:
                    entity = await client_manager.client.get_input_entity(group.id)
            except Exception:
                pass

            # Strategy 2: resolve by username (works for public groups)
            if entity is None and group.username:
                try:
                    entity = await client_manager.client.get_input_entity(group.username)
                except (ValueError, TypeError):
                    pass

            # Strategy 3: construct InputPeer from stored data
            if entity is None:
                if group.entity_type == 'channel' and group.access_hash is not None:
                    entity = InputPeerChannel(group.id, group.access_hash)
                elif group.entity_type == 'chat':
                    entity = InputPeerChat(group.id)
                else:
                    entity = group.id

            await client_manager.client.send_message(entity, message)

            return MessageResult(
                group_id=group.id,
                group_name=group.name,
                status=SendStatus.SENT,
                message=message
            )

        except FloodWaitError as e:
            logger.warning(f"Rate limited, waiting {e.seconds} seconds")
            await asyncio.sleep(e.seconds)
            if self._should_stop:
                return MessageResult(
                    group_id=group.id,
                    group_name=group.name,
                    status=SendStatus.RATE_LIMITED,
                    message=message,
                    error=f"Rate limited: stopped during wait ({e.seconds}s)"
                )
            try:
                await client_manager.client.send_message(entity, message)
                return MessageResult(
                    group_id=group.id,
                    group_name=group.name,
                    status=SendStatus.SENT,
                    message=message
                )
            except Exception as retry_err:
                logger.error(f"Rate-limit retry failed for {group.name}: {retry_err}")
                return MessageResult(
                    group_id=group.id,
                    group_name=group.name,
                    status=SendStatus.FAILED,
                    message=message,
                    error=f"Rate-limit retry failed: {retry_err}"
                )

        except MessageNotModifiedError:
            return MessageResult(
                group_id=group.id,
                group_name=group.name,
                status=SendStatus.SKIPPED,
                message=message,
                error="Message not modified"
            )

        except Exception as e:
            from telethon.errors import SessionRevokedError, AuthKeyError
            if isinstance(e, (SessionRevokedError, AuthKeyError)):
                raise  # propagate up so automation_worker can mark session revoked
            logger.error(f"Failed to send message to {group.name}: {e}")
            return MessageResult(
                group_id=group.id,
                group_name=group.name,
                status=SendStatus.FAILED,
                message=message,
                error=str(e)
            )

    def get_results_summary(self) -> Dict[str, Any]:
        """Get summary of sending results"""
        processed = len(self._results)
        return {
            'total': self._total_groups,
            'sent': self._sent_count,
            'failed': self._failed_count,
            'pending': max(0, self._total_groups - processed),
            'progress': self.progress,
            'is_running': self._is_running,
            'is_paused': self._is_paused
        }


# Global sender instance
sender = MessageSender()

__all__ = [
    'SendStatus',
    'MessageResult',
    'AutomationConfig',
    'MessageSender',
    'sender'
]
