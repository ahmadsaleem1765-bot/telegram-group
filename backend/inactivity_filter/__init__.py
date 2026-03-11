"""
Inactivity Filter Module

Filters groups based on their last message timestamp and user-defined threshold.
"""

import logging
from typing import List, Optional
from dataclasses import dataclass
from datetime import datetime, timedelta

from backend.group_scanner import Group, GroupScanner

logger = logging.getLogger(__name__)


@dataclass
class InactivityThreshold:
    """Defines the threshold for determining inactive groups"""
    date: datetime
    
    @classmethod
    def from_datetime(cls, dt: datetime) -> 'InactivityThreshold':
        return cls(date=dt)
    
    @classmethod
    def from_date_string(cls, date_str: str, time_str: str = "00:00") -> 'InactivityThreshold':
        """Create threshold from date and time strings"""
        date_format = "%Y-%m-%d"
        time_format = "%H:%M"
        
        dt = datetime.strptime(f"{date_str} {time_str}", f"{date_format} {time_format}")
        return cls(date=dt)
    
    def is_inactive(self, last_message_time: Optional[datetime]) -> bool:
        """Check if a group is inactive based on last message time"""
        if last_message_time is None:
            # No messages = definitely inactive
            return True
        return last_message_time <= self.date
    
    def __str__(self) -> str:
        return self.date.strftime("%Y-%m-%d %H:%M")


class InactivityFilter:
    """Filters groups based on inactivity threshold"""
    
    def __init__(self, scanner: GroupScanner):
        self._scanner = scanner
        self._threshold: Optional[InactivityThreshold] = None
        self._inactive_groups: List[Group] = []
        self._active_groups: List[Group] = []
    
    @property
    def threshold(self) -> Optional[InactivityThreshold]:
        return self._threshold
    
    @property
    def inactive_groups(self) -> List[Group]:
        return self._inactive_groups
    
    @property
    def active_groups(self) -> List[Group]:
        return self._active_groups
    
    @property
    def total_groups(self) -> int:
        return len(self._scanner.groups)
    
    @property
    def inactive_count(self) -> int:
        return len(self._inactive_groups)
    
    @property
    def active_count(self) -> int:
        return len(self._active_groups)
    
    def set_threshold(self, date: datetime) -> None:
        """Set the inactivity threshold"""
        self._threshold = InactivityThreshold.from_datetime(date)
        logger.info(f"Set inactivity threshold to: {self._threshold}")
    
    def set_threshold_from_strings(self, date_str: str, time_str: str = "00:00") -> None:
        """Set threshold from date and time strings"""
        self._threshold = InactivityThreshold.from_date_string(date_str, time_str)
        logger.info(f"Set inactivity threshold to: {self._threshold}")
    
    def filter_groups(
        self, 
        groups: Optional[List[Group]] = None,
        mark_inactive: bool = True
    ) -> tuple[List[Group], List[Group]]:
        """
        Filter groups into active and inactive based on threshold.
        
        Args:
            groups: List of groups to filter (defaults to scanner's groups)
            mark_inactive: Whether to mark groups as inactive in the Group object
            
        Returns:
            Tuple of (active_groups, inactive_groups)
        """
        if self._threshold is None:
            raise ValueError("Inactivity threshold not set. Call set_threshold() first.")
        
        groups_to_filter = groups if groups is not None else self._scanner.groups
        
        active = []
        inactive = []
        
        for group in groups_to_filter:
            is_inactive = self._threshold.is_inactive(group.last_message_time)
            
            if mark_inactive:
                group.is_active = not is_inactive
            
            if is_inactive:
                inactive.append(group)
            else:
                active.append(group)
        
        self._active_groups = active
        self._inactive_groups = inactive
        
        logger.info(
            f"Filtered {len(groups_to_filter)} groups: "
            f"{len(active)} active, {len(inactive)} inactive"
        )
        
        return active, inactive
    
    def get_inactive_groups(self) -> List[Group]:
        """Get list of inactive groups"""
        return self._inactive_groups
    
    def get_active_groups(self) -> List[Group]:
        """Get list of active groups"""
        return self._active_groups
    
    def get_groups_by_status(self, active: bool) -> List[Group]:
        """Get groups filtered by active status"""
        return self._active_groups if active else self._inactive_groups
    
    def get_statistics(self) -> dict:
        """Get filter statistics"""
        return {
            'total_groups': self.total_groups,
            'active_groups': self.active_count,
            'inactive_groups': self.inactive_count,
            'threshold': str(self._threshold) if self._threshold else None,
            'threshold_datetime': (
                self._threshold.date.isoformat() 
                if self._threshold else None
            )
        }
    
    def reset(self):
        """Reset the filter"""
        self._threshold = None
        self._inactive_groups = []
        self._active_groups = []


# Factory function to create filter from scanner
def create_inactivity_filter(scanner: GroupScanner) -> InactivityFilter:
    """Create a new InactivityFilter instance"""
    return InactivityFilter(scanner)


__all__ = [
    'InactivityThreshold', 
    'InactivityFilter', 
    'create_inactivity_filter'
]
