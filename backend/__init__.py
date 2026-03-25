"""
Backend Package

Telegram automation backend with modular architecture.
"""

from .telegram_client import client_manager, TelegramClientManager, TelegramUser
from .group_scanner import scanner, GroupScanner, Group
from .inactivity_filter import create_inactivity_filter, InactivityFilter, InactivityThreshold
from .message_sender import sender, MessageSender, AutomationConfig, MessageResult, SendStatus
from .scheduler import scheduler, Scheduler, Schedule, ScheduleType
from .content_manager import ContentManager, AdContent
from .channel_adapter import (
    ChannelAdapter, TelegramAdapter, DeliveryEngine,
    DeliveryResult, DeliveryStatus, Destination,
)
from .ad_scheduler import AdScheduler, DeliveryLedger

__all__ = [
    # Telegram Client
    'client_manager',
    'TelegramClientManager',
    'TelegramUser',

    # Group Scanner
    'scanner',
    'GroupScanner',
    'Group',

    # Inactivity Filter
    'create_inactivity_filter',
    'InactivityFilter',
    'InactivityThreshold',

    # Message Sender
    'sender',
    'MessageSender',
    'AutomationConfig',
    'MessageResult',
    'SendStatus',

    # Scheduler
    'scheduler',
    'Scheduler',
    'Schedule',
    'ScheduleType',

    # Content Manager
    'ContentManager',
    'AdContent',

    # Channel Adapter
    'ChannelAdapter',
    'TelegramAdapter',
    'DeliveryEngine',
    'DeliveryResult',
    'DeliveryStatus',
    'Destination',

    # Ad Scheduler
    'AdScheduler',
    'DeliveryLedger',
]
