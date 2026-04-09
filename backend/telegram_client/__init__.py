"""
Telegram Client Module

Handles authentication and communication with Telegram API using Telethon.
"""

import asyncio
import logging
from typing import Optional, List

from dataclasses import dataclass

from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import (
    SessionPasswordNeededError,
    PhoneCodeInvalidError,
    ApiIdInvalidError,
    FloodWaitError,
    SessionRevokedError,
    AuthKeyError,
)
from telethon.tl.types import Chat, Channel, Dialog

from config import config

logger = logging.getLogger(__name__)


@dataclass
class TelegramUser:
    """Represents authenticated Telegram user"""
    id: int
    first_name: str
    last_name: Optional[str]
    username: Optional[str]
    phone: Optional[str]

    @property
    def display_name(self) -> str:
        name = self.first_name
        if self.last_name:
            name += f" {self.last_name}"
        return name


class TelegramClientManager:
    """Manages Telegram client lifecycle and authentication"""

    def __init__(self):
        self._client: Optional[TelegramClient] = None
        self._user: Optional[TelegramUser] = None
        self._is_authenticated = False
        self._session_revoked = False

    @property
    def is_authenticated(self) -> bool:
        return self._is_authenticated

    @property
    def session_revoked(self) -> bool:
        return self._session_revoked

    def mark_session_revoked(self):
        """Mark session as revoked — called when Telegram invalidates the session."""
        self._is_authenticated = False
        self._session_revoked = True
        self._user = None
        logger.critical("Session has been revoked by Telegram. Re-authentication required.")

    @property
    def client(self) -> Optional[TelegramClient]:
        return self._client

    @property
    def user(self) -> Optional[TelegramUser]:
        return self._user

    async def start_with_session(self, session_string: str) -> bool:
        """
        Start client using existing session string.

        Args:
            session_string: Telegram session string

        Returns:
            True if authentication successful
        """
        if not config.is_configured:
            logger.error("API_ID and API_HASH must be configured")
            return False

        # Disconnect existing client if any (e.g., after session revocation)
        if self._client is not None:
            try:
                await self._client.disconnect()
            except Exception:
                pass
            self._client = None
            self._is_authenticated = False
            self._session_revoked = False

        try:
            # Create client with session string
            self._client = TelegramClient(
                StringSession(session_string),
                int(config.api_id),
                config.api_hash
            )

            await self._client.connect()

            # Verify authorization
            if await self._client.is_user_authorized():
                me = await self._client.get_me()
                self._user = TelegramUser(
                    id=me.id,
                    first_name=me.first_name,
                    last_name=me.last_name,
                    username=me.username,
                    phone=me.phone
                )
                self._is_authenticated = True
                self._session_revoked = False
                asyncio.ensure_future(self._watch_disconnection())
                logger.info(f"Authenticated as {self._user.display_name}")
                return True

            return False

        except ApiIdInvalidError:
            logger.error("Invalid API_ID or API_HASH")
            return False
        except Exception as e:
            logger.error(f"Failed to authenticate: {e}")
            return False

    async def _watch_disconnection(self):
        """Monitor client connection and detect session revocation on disconnect."""
        client = self._client
        if client is None:
            return
        try:
            await client.disconnected
        except (SessionRevokedError, AuthKeyError):
            self.mark_session_revoked()
        except Exception as e:
            if self._is_authenticated:
                logger.warning(f"Telegram client disconnected unexpectedly: {e}")

    async def start_with_phone(self, phone: str) -> str:
        """
        Start authentication with phone number.
        Returns request_id for code verification.
        """
        if not config.is_configured:
            raise ValueError("API_ID and API_HASH must be configured")

        # Remove any non-digit characters from phone
        phone = ''.join(filter(str.isdigit, phone))

        self._client = TelegramClient(
            StringSession(),
            int(config.api_id),
            config.api_hash
        )

        await self._client.connect()
        try:
            sent_code = await self._client.send_code_request(phone)
        except FloodWaitError as e:
            await self._client.disconnect()
            minutes, seconds = divmod(e.seconds, 60)
            hours, minutes = divmod(minutes, 60)
            wait_str = f"{hours}h {minutes}m {seconds}s" if hours else f"{minutes}m {seconds}s"
            raise ValueError(
                f"Too many login attempts. Telegram requires a wait of {wait_str} "
                f"({e.seconds} seconds) before sending another code to this number."
            )

        code_type = type(sent_code.type).__name__  # e.g. SentCodeTypeApp, SentCodeTypeSms
        return sent_code.phone_code_hash, code_type

    async def verify_code(self, phone: str, code: str, phone_code_hash: str) -> Optional[str]:
        """Verify the SMS code"""
        try:
            phone = ''.join(filter(str.isdigit, phone))
            await self._client.sign_in(phone, code, phone_code_hash=phone_code_hash)
            me = await self._client.get_me()
            self._user = TelegramUser(
                id=me.id,
                first_name=me.first_name,
                last_name=me.last_name,
                username=me.username,
                phone=me.phone
            )
            self._is_authenticated = True

            # Generate and return session string
            session_str = self._client.session.save()
            return session_str

        except SessionPasswordNeededError:
            logger.error("Two-factor authentication required")
            raise
        except PhoneCodeInvalidError:
            logger.error("Invalid verification code")
            return None

    async def verify_password(self, password: str) -> Optional[str]:
        """Verify two-factor authentication password"""
        try:
            await self._client.sign_in(password=password)
            me = await self._client.get_me()
            self._user = TelegramUser(
                id=me.id,
                first_name=me.first_name,
                last_name=me.last_name,
                username=me.username,
                phone=me.phone
            )
            self._is_authenticated = True

            # Generate and return session string
            session_str = self._client.session.save()
            return session_str

        except Exception as e:
            logger.error(f"Password verification failed: {e}")
            raise

    def get_session_string(self) -> Optional[str]:
        """Get current session string"""
        if self._client:
            return self._client.session.save()
        return None

    async def disconnect(self):
        """Disconnect the client"""
        if self._client:
            await self._client.disconnect()
            self._client = None
            self._is_authenticated = False
            self._user = None

    async def get_dialogs(self, limit: int = 100) -> List[Dialog]:
        """Get all dialogs (conversations)"""
        if not self._client or not self._is_authenticated:
            raise RuntimeError("Client not authenticated")

        dialogs = await self._client.get_dialogs(limit=limit)
        return dialogs

    async def get_groups(self) -> List[Chat]:
        """Get all groups the user is member of"""
        if not self._client or not self._is_authenticated:
            raise RuntimeError("Client not authenticated")

        groups = []
        async for dialog in self._client.iter_dialogs():
            entity = dialog.entity
            # Check if it's a group (channel or megagroup)
            if isinstance(entity, Channel) and entity.megagroup:
                groups.append(entity)
            elif isinstance(entity, Chat):
                groups.append(entity)

        return groups


# Global client manager instance
client_manager = TelegramClientManager()


__all__ = [
    'TelegramClientManager',
    'TelegramUser',
    'client_manager',
    'StringSession'
]
