"""
Content Manager Module

Manages dynamic ad/poster content with hot-swapping support.
Content is stored in a watched directory with a JSON manifest for metadata.
Supports daily rotation, active flags, and multimedia assets.
"""

import json
import os
import logging
import hashlib
from typing import List, Optional, Dict, Any
from dataclasses import dataclass, field
from datetime import date, datetime, timezone

logger = logging.getLogger(__name__)


@dataclass
class AdContent:
    """Represents a single advertisement or poster."""

    id: str
    title: str
    message: str = ""
    media_path: Optional[str] = None
    media_type: Optional[str] = None  # "photo", "video", "document"
    is_active: bool = True
    priority: int = 0
    schedule_date: Optional[str] = None  # ISO date "YYYY-MM-DD" or None for any day
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    tags: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "message": self.message,
            "media_path": self.media_path,
            "media_type": self.media_type,
            "is_active": self.is_active,
            "priority": self.priority,
            "schedule_date": self.schedule_date,
            "created_at": self.created_at,
            "tags": self.tags,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AdContent":
        return cls(
            id=data.get("id", ""),
            title=data.get("title", ""),
            message=data.get("message", ""),
            media_path=data.get("media_path"),
            media_type=data.get("media_type"),
            is_active=data.get("is_active", True),
            priority=data.get("priority", 0),
            schedule_date=data.get("schedule_date"),
            created_at=data.get(
                "created_at", datetime.now(timezone.utc).isoformat()
            ),
            tags=data.get("tags", []),
        )

    @property
    def content_hash(self) -> str:
        """Deterministic hash of the content for idempotency checks."""
        raw = f"{self.id}:{self.message}:{self.media_path or ''}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]


MANIFEST_FILENAME = "manifest.json"


class ContentManager:
    """Manages ad content from a directory with a JSON manifest.

    The content directory structure:
        content/
        ├── manifest.json       # Metadata for all ads
        ├── poster1.jpg         # Media assets
        ├── poster2.png
        └── ...

    The manifest.json is the source of truth. Media files are referenced
    by relative path within the content directory.
    """

    def __init__(self, content_dir: str) -> None:
        self._content_dir = os.path.abspath(content_dir)
        self._ads: List[AdContent] = []
        self._manifest_mtime: float = 0.0
        os.makedirs(self._content_dir, exist_ok=True)
        self._ensure_manifest()
        self.reload()

    @property
    def content_dir(self) -> str:
        return self._content_dir

    @property
    def manifest_path(self) -> str:
        return os.path.join(self._content_dir, MANIFEST_FILENAME)

    def _ensure_manifest(self) -> None:
        """Create an empty manifest if none exists."""
        if not os.path.exists(self.manifest_path):
            self._write_manifest([])
            logger.info(
                "Created empty manifest at %s", self.manifest_path
            )

    def _write_manifest(self, ads_data: List[Dict[str, Any]]) -> None:
        """Atomically write manifest to disk."""
        tmp = self.manifest_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"ads": ads_data}, f, indent=2)
        if os.path.exists(self.manifest_path):
            os.remove(self.manifest_path)
        os.rename(tmp, self.manifest_path)

    def reload(self) -> None:
        """Reload the manifest from disk (hot-swap support)."""
        try:
            with open(self.manifest_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            ads_data = data.get("ads", [])
            self._ads = [AdContent.from_dict(a) for a in ads_data]
            self._manifest_mtime = os.path.getmtime(self.manifest_path)
            logger.info(
                "Loaded %d ads from manifest", len(self._ads)
            )
        except Exception as e:
            logger.error("Failed to load manifest: %s", e)
            self._ads = []

    def check_for_updates(self) -> bool:
        """Check if manifest has been modified on disk and reload if so.

        Returns True if a reload happened.
        """
        try:
            current_mtime = os.path.getmtime(self.manifest_path)
            if current_mtime > self._manifest_mtime:
                self.reload()
                return True
        except OSError:
            pass
        return False

    def get_all_ads(self) -> List[AdContent]:
        """Return all ads regardless of status."""
        self.check_for_updates()
        return list(self._ads)

    def get_active_ads(self) -> List[AdContent]:
        """Return only active ads."""
        self.check_for_updates()
        return [a for a in self._ads if a.is_active]

    def get_ad_for_date(self, target_date: Optional[date] = None) -> Optional[AdContent]:
        """Select the best ad for a given date.

        Selection priority:
        1. Active ad with matching schedule_date
        2. Active ad with no schedule_date (general pool), rotated by day-of-year
        3. None if no active ads exist
        """
        self.check_for_updates()
        target = target_date or date.today()
        target_iso = target.isoformat()

        # Priority 1: exact date match
        dated = [
            a for a in self._ads
            if a.is_active and a.schedule_date == target_iso
        ]
        if dated:
            # Highest priority wins
            dated.sort(key=lambda a: a.priority, reverse=True)
            return dated[0]

        # Priority 2: general pool rotation
        general = [
            a for a in self._ads
            if a.is_active and a.schedule_date is None
        ]
        if not general:
            return None

        general.sort(key=lambda a: (-a.priority, a.id))
        day_index = target.timetuple().tm_yday % len(general)
        return general[day_index]

    def get_ad_by_id(self, ad_id: str) -> Optional[AdContent]:
        """Find an ad by its ID."""
        self.check_for_updates()
        for ad in self._ads:
            if ad.id == ad_id:
                return ad
        return None

    def add_ad(self, ad: AdContent) -> AdContent:
        """Add a new ad and persist."""
        if any(a.id == ad.id for a in self._ads):
            raise ValueError(f"Ad with id '{ad.id}' already exists")
        self._ads.append(ad)
        self._save()
        logger.info("Added ad: %s (id=%s)", ad.title, ad.id)
        return ad

    def update_ad(self, ad_id: str, updates: Dict[str, Any]) -> Optional[AdContent]:
        """Update an existing ad's fields and persist."""
        ad = self.get_ad_by_id(ad_id)
        if not ad:
            return None
        for key, value in updates.items():
            if hasattr(ad, key) and key != "id":
                setattr(ad, key, value)
        self._save()
        logger.info("Updated ad: %s", ad_id)
        return ad

    def delete_ad(self, ad_id: str) -> bool:
        """Remove an ad and persist."""
        initial = len(self._ads)
        self._ads = [a for a in self._ads if a.id != ad_id]
        if len(self._ads) < initial:
            self._save()
            logger.info("Deleted ad: %s", ad_id)
            return True
        return False

    def resolve_media_path(self, ad: AdContent) -> Optional[str]:
        """Resolve a relative media_path to an absolute path.

        Returns None if the media file does not exist.
        """
        if not ad.media_path:
            return None
        full = os.path.join(self._content_dir, ad.media_path)
        if os.path.isfile(full):
            return full
        logger.warning(
            "Media file not found for ad %s: %s", ad.id, full
        )
        return None

    def _save(self) -> None:
        """Persist current ads to manifest."""
        self._write_manifest([a.to_dict() for a in self._ads])
        self._manifest_mtime = os.path.getmtime(self.manifest_path)


__all__ = ["AdContent", "ContentManager"]
