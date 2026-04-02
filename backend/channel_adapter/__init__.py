"""
Channel Adapter Module

Provides a unified interface for delivering content to multiple
destination types (Telegram groups, Discord channels, etc.).
Includes exponential backoff retry logic.
"""

import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

logger = logging.getLogger(__name__)


class DeliveryStatus(Enum):
    """Outcome of a delivery attempt."""

    SUCCESS = "success"
    FAILED = "failed"
    RETRYING = "retrying"
    SKIPPED = "skipped"
    FLOOD_WAITED = "flood_waited"  # Telegram rate-limit; retry scheduled automatically


@dataclass
class DeliveryResult:
    """Result of delivering content to a single destination."""

    destination_id: str
    destination_name: str
    destination_type: str
    status: DeliveryStatus
    content_id: str
    timestamp: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    attempts: int = 1
    error: Optional[str] = None
    flood_wait_seconds: Optional[int] = None  # Set when status is FLOOD_WAITED

    def to_dict(self) -> Dict[str, Any]:
        return {
            "destination_id": self.destination_id,
            "destination_name": self.destination_name,
            "destination_type": self.destination_type,
            "status": self.status.value,
            "content_id": self.content_id,
            "timestamp": self.timestamp.isoformat(),
            "attempts": self.attempts,
            "error": self.error,
            "flood_wait_seconds": self.flood_wait_seconds,
        }


@dataclass
class Destination:
    """A target channel/group for content delivery."""

    id: str
    name: str
    type: str  # "telegram", "discord", etc.
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "type": self.type,
            "metadata": self.metadata,
        }


class ChannelAdapter(ABC):
    """Abstract base class for channel delivery adapters.

    Each platform (Telegram, Discord, etc.) implements this interface.
    """

    @property
    @abstractmethod
    def adapter_type(self) -> str:
        """Return the adapter type identifier (e.g. 'telegram')."""
        ...

    @abstractmethod
    async def send_text(
        self, destination_id: str, text: str
    ) -> None:
        """Send a text message to the destination."""
        ...

    @abstractmethod
    async def send_media(
        self,
        destination_id: str,
        media_path: str,
        media_type: str,
        caption: Optional[str] = None,
    ) -> None:
        """Send a media file with optional caption."""
        ...

    @abstractmethod
    async def is_available(self) -> bool:
        """Check if the adapter is connected and ready."""
        ...


class TelegramAdapter(ChannelAdapter):
    """Telegram delivery adapter using Telethon client."""

    def __init__(self, client_manager: Any) -> None:
        self._client_manager = client_manager

    @property
    def adapter_type(self) -> str:
        return "telegram"

    async def _resolve_entity(self, client: Any, destination_id: str) -> Any:
        """Resolve a destination ID to a Telethon entity.

        Tries the session cache first (via PeerChannel/PeerChat), then falls
        back to a raw-int lookup that Telethon can satisfy even without cache
        if the entity was recently seen.
        """
        from telethon.tl.types import PeerChannel, PeerChat
        raw_id = int(destination_id)
        # Try channel cache lookup first
        for peer_cls in (PeerChannel, PeerChat):
            try:
                return await client.get_input_entity(peer_cls(raw_id))
            except Exception:
                pass
        # Last resort: raw int (works if Telethon cache has it)
        return raw_id

    async def send_text(self, destination_id: str, text: str) -> None:
        client = self._client_manager.client
        entity = await self._resolve_entity(client, destination_id)
        await client.send_message(entity, text)

    async def send_media(
        self,
        destination_id: str,
        media_path: str,
        media_type: str,
        caption: Optional[str] = None,
    ) -> None:
        client = self._client_manager.client
        entity = await self._resolve_entity(client, destination_id)
        await client.send_file(entity, media_path, caption=caption)

    async def is_available(self) -> bool:
        return self._client_manager.is_authenticated


class DeliveryEngine:
    """Orchestrates content delivery across adapters with retry logic.

    Features:
    - Exponential backoff on failure (base * 2^attempt, capped)
    - Configurable max retries
    - Per-destination delivery results
    """

    DEFAULT_MAX_RETRIES: int = 3
    DEFAULT_BACKOFF_BASE: float = 2.0
    DEFAULT_BACKOFF_CAP: float = 60.0
    DEFAULT_INTER_SEND_DELAY: float = 5.0

    def __init__(
        self,
        max_retries: int = DEFAULT_MAX_RETRIES,
        backoff_base: float = DEFAULT_BACKOFF_BASE,
        backoff_cap: float = DEFAULT_BACKOFF_CAP,
        inter_send_delay: float = DEFAULT_INTER_SEND_DELAY,
    ) -> None:
        self._adapters: Dict[str, ChannelAdapter] = {}
        self._max_retries = max_retries
        self._backoff_base = backoff_base
        self._backoff_cap = backoff_cap
        self._inter_send_delay = inter_send_delay

    def register_adapter(self, adapter: ChannelAdapter) -> None:
        """Register a channel adapter."""
        self._adapters[adapter.adapter_type] = adapter
        logger.info("Registered adapter: %s", adapter.adapter_type)

    def get_adapter(self, adapter_type: str) -> Optional[ChannelAdapter]:
        return self._adapters.get(adapter_type)

    def _calculate_backoff(self, attempt: int) -> float:
        """Exponential backoff: base * 2^attempt, capped."""
        delay = self._backoff_base * (2 ** attempt)
        return min(delay, self._backoff_cap)

    async def deliver(
        self,
        destination: Destination,
        content_id: str,
        text: Optional[str] = None,
        media_path: Optional[str] = None,
        media_type: Optional[str] = None,
    ) -> DeliveryResult:
        """Deliver content to a single destination with retry.

        Args:
            destination: Target destination.
            content_id: ID of the ad content being delivered.
            text: Text message to send.
            media_path: Absolute path to media file.
            media_type: Type of media (photo, video, document).

        Returns:
            DeliveryResult with final status.
        """
        adapter = self._adapters.get(destination.type)
        if not adapter:
            logger.error(
                "No adapter registered for type: %s", destination.type
            )
            return DeliveryResult(
                destination_id=destination.id,
                destination_name=destination.name,
                destination_type=destination.type,
                status=DeliveryStatus.SKIPPED,
                content_id=content_id,
                error=f"No adapter for type '{destination.type}'",
            )

        last_error: Optional[str] = None
        for attempt in range(self._max_retries + 1):
            try:
                if media_path and media_type:
                    await adapter.send_media(
                        destination.id, media_path, media_type, caption=text
                    )
                elif text:
                    await adapter.send_text(destination.id, text)
                else:
                    return DeliveryResult(
                        destination_id=destination.id,
                        destination_name=destination.name,
                        destination_type=destination.type,
                        status=DeliveryStatus.SKIPPED,
                        content_id=content_id,
                        error="No text or media to send",
                    )

                logger.info(
                    "Delivered content %s to %s (%s) on attempt %d",
                    content_id,
                    destination.name,
                    destination.type,
                    attempt + 1,
                )
                return DeliveryResult(
                    destination_id=destination.id,
                    destination_name=destination.name,
                    destination_type=destination.type,
                    status=DeliveryStatus.SUCCESS,
                    content_id=content_id,
                    attempts=attempt + 1,
                )

            except Exception as e:
                last_error = str(e)
                # Telethon FloodWaitError carries the exact required wait in seconds.
                # Return FLOOD_WAITED immediately so the caller can schedule a precise
                # retry instead of wasting attempts against a hard Telegram block.
                try:
                    from telethon.errors import FloodWaitError
                    if isinstance(e, FloodWaitError):
                        logger.warning(
                            "Delivery to %s hit Telegram flood limit: must wait %ds.",
                            destination.name,
                            e.seconds,
                        )
                        return DeliveryResult(
                            destination_id=destination.id,
                            destination_name=destination.name,
                            destination_type=destination.type,
                            status=DeliveryStatus.FLOOD_WAITED,
                            content_id=content_id,
                            attempts=attempt + 1,
                            error=last_error,
                            flood_wait_seconds=e.seconds,
                        )
                except ImportError:
                    pass

                if attempt < self._max_retries:
                    backoff = self._calculate_backoff(attempt)
                    logger.warning(
                        "Delivery to %s failed (attempt %d/%d): %s. "
                        "Retrying in %.1fs",
                        destination.name,
                        attempt + 1,
                        self._max_retries + 1,
                        last_error,
                        backoff,
                    )
                    await asyncio.sleep(backoff)
                else:
                    logger.error(
                        "Delivery to %s failed after %d attempts: %s",
                        destination.name,
                        self._max_retries + 1,
                        last_error,
                    )

        return DeliveryResult(
            destination_id=destination.id,
            destination_name=destination.name,
            destination_type=destination.type,
            status=DeliveryStatus.FAILED,
            content_id=content_id,
            attempts=self._max_retries + 1,
            error=last_error,
        )

    async def deliver_to_many(
        self,
        destinations: List[Destination],
        content_id: str,
        text: Optional[str] = None,
        media_path: Optional[str] = None,
        media_type: Optional[str] = None,
    ) -> List[DeliveryResult]:
        """Deliver content to multiple destinations sequentially with delays."""
        results: List[DeliveryResult] = []
        for i, dest in enumerate(destinations):
            if i > 0:
                await asyncio.sleep(self._inter_send_delay)
            result = await self.deliver(
                dest, content_id, text, media_path, media_type
            )
            results.append(result)
        return results


__all__ = [
    "ChannelAdapter",
    "TelegramAdapter",
    "DeliveryEngine",
    "DeliveryResult",
    "DeliveryStatus",
    "Destination",
]
