"""
Group Scanner Module

Scans Telegram groups and retrieves metadata including last message timestamps.
"""

import logging
import asyncio
from typing import List, Optional, Dict, Any, Callable
from dataclasses import dataclass, asdict
from datetime import datetime

from telethon.tl.types import Channel, Chat, Message
from telethon.errors import FloodWaitError, ChannelInvalidError

from backend.telegram_client import client_manager

logger = logging.getLogger(__name__)


@dataclass
class Group:
    """Represents a Telegram group with its metadata"""
    id: int
    name: str
    username: Optional[str]
    last_message_time: Optional[datetime]
    member_count: Optional[int]
    is_active: bool = False
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'name': self.name,
            'username': self.username,
            'last_message_time': self.last_message_time.isoformat() if self.last_message_time else None,
            'member_count': self.member_count,
            'is_active': self.is_active
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Group':
        lmt = data.get('last_message_time')
        if lmt:
            lmt = datetime.fromisoformat(lmt)
        return cls(
            id=data['id'],
            name=data['name'],
            username=data.get('username'),
            last_message_time=lmt,
            member_count=data.get('member_count'),
            is_active=data.get('is_active', False)
        )


class GroupScanner:
    """Scans Telegram groups and retrieves their metadata"""
    
    def __init__(self):
        self._groups: List[Group] = []
        self._is_scanning = False
        self._scan_progress = 0
    
    @property
    def groups(self) -> List[Group]:
        return self._groups
    
    @property
    def is_scanning(self) -> bool:
        return self._is_scanning
    
    @property
    def scan_progress(self) -> float:
        return self._scan_progress
    
    async def scan_all_groups(
        self, 
        progress_callback: Optional[Callable] = None,
        max_groups: int = 500
    ) -> List[Group]:
        """
        Scan all groups and retrieve last message timestamps.
        
        Args:
            progress_callback: Optional callback for progress updates
            max_groups: Maximum number of groups to scan
            
        Returns:
            List of Group objects with metadata
        """
        if not client_manager.is_authenticated:
            raise RuntimeError("Telegram client not authenticated")
        
        self._is_scanning = True
        self._groups = []
        
        try:
            # Get all dialogs
            dialogs = await client_manager.client.get_dialogs(limit=max_groups)
            
            # Filter for groups only
            group_dialogs = []
            for dialog in dialogs:
                entity = dialog.entity
                if isinstance(entity, Channel) and entity.megagroup:
                    group_dialogs.append((dialog, entity))
                elif isinstance(entity, Chat):
                    group_dialogs.append((dialog, entity))
            
            total_groups = len(group_dialogs)
            logger.info(f"Found {total_groups} groups to scan")
            
            # Scan each group for last message
            for idx, (dialog, entity) in enumerate(group_dialogs):
                try:
                    group = await self._scan_single_group(dialog, entity)
                    if group:
                        self._groups.append(group)
                    
                    # Update progress
                    self._scan_progress = (idx + 1) / total_groups
                    
                    if progress_callback:
                        progress_callback(
                            idx + 1, 
                            total_groups, 
                            getattr(group, 'name', 'Unknown') if group else "Unknown"
                        )
                    
                    # Small delay to avoid rate limits
                    await asyncio.sleep(0.1)
                    
                except FloodWaitError as e:
                    logger.warning(f"Rate limited, waiting {e.seconds} seconds")
                    await asyncio.sleep(e.seconds)
                except Exception as e:
                    logger.error(f"Error scanning group {dialog.name}: {e}")
            
            logger.info(f"Scan complete. Found {len(self._groups)} groups")
            return self._groups
            
        finally:
            self._is_scanning = False
    
    async def _scan_single_group(
        self, 
        dialog, 
        entity: Channel | Chat
    ) -> Optional[Group]:
        """Scan a single group for its last message timestamp"""
        
        try:
            # Get group info
            group_id = entity.id
            group_name = getattr(entity, 'title', None) or dialog.name
            group_username = getattr(entity, 'username', None)
            member_count = getattr(entity, 'participants_count', None)
            
            # Try to get the last message
            last_message_time = None
            try:
                # Get the last message from the group
                async for message in client_manager.client.iter_messages(
                    entity, 
                    limit=1,
                    wait_time=0
                ):
                    if message:
                        last_message_time = message.date
                        break
            except (FloodWaitError, ChannelInvalidError) as e:
                logger.warning(f"Could not get last message for {group_name}: {e}")
            except Exception as e:
                logger.debug(f"Could not get messages for {group_name}: {e}")
            
            return Group(
                id=group_id,
                name=group_name,
                username=group_username,
                last_message_time=last_message_time,
                member_count=member_count,
                is_active=False
            )
            
        except Exception as e:
            logger.error(f"Error scanning group {getattr(entity, 'title', 'unknown')}: {e}")
            return None
    
    def get_group_by_id(self, group_id: int) -> Optional[Group]:
        """Get a group by its ID"""
        for group in self._groups:
            if group.id == group_id:
                return group
        return None
    
    def clear(self):
        """Clear scanned groups"""
        self._groups = []
        self._scan_progress = 0


# Global scanner instance
scanner = GroupScanner()

__all__ = ['Group', 'GroupScanner', 'scanner']
