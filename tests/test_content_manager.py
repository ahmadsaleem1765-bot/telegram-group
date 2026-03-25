"""
Unit tests for the Content Manager module.

Tests content loading, daily rotation, hot-swapping, and CRUD operations.
All tests are idempotent and use temporary directories.
"""

import json
import os
from datetime import date

import pytest

from backend.content_manager import AdContent, ContentManager


@pytest.fixture
def content_dir(tmp_path):
    """Create a temporary content directory."""
    return str(tmp_path / "content")


@pytest.fixture
def sample_ads():
    """Sample ad data for testing."""
    return [
        {
            "id": "ad-001",
            "title": "Morning Promo",
            "message": "Good morning! Check out our deals.",
            "media_path": None,
            "media_type": None,
            "is_active": True,
            "priority": 10,
            "schedule_date": None,
            "tags": ["promo"],
        },
        {
            "id": "ad-002",
            "title": "Weekend Special",
            "message": "Weekend sale is here!",
            "media_path": "poster.jpg",
            "media_type": "photo",
            "is_active": True,
            "priority": 5,
            "schedule_date": None,
            "tags": ["sale"],
        },
        {
            "id": "ad-003",
            "title": "Holiday Ad",
            "message": "Happy holidays from our team!",
            "media_path": None,
            "media_type": None,
            "is_active": True,
            "priority": 0,
            "schedule_date": "2026-12-25",
            "tags": ["holiday"],
        },
        {
            "id": "ad-inactive",
            "title": "Old Promo",
            "message": "This is inactive.",
            "is_active": False,
            "priority": 100,
        },
    ]


@pytest.fixture
def manager(content_dir, sample_ads):
    """Create a ContentManager with sample data."""
    os.makedirs(content_dir, exist_ok=True)
    manifest_path = os.path.join(content_dir, "manifest.json")
    with open(manifest_path, "w") as f:
        json.dump({"ads": sample_ads}, f)
    return ContentManager(content_dir)


class TestAdContent:
    def test_from_dict_roundtrip(self, sample_ads):
        ad = AdContent.from_dict(sample_ads[0])
        result = ad.to_dict()
        assert result["id"] == "ad-001"
        assert result["title"] == "Morning Promo"
        assert result["is_active"] is True

    def test_content_hash_deterministic(self):
        ad = AdContent(id="x", title="T", message="Hello")
        h1 = ad.content_hash
        h2 = ad.content_hash
        assert h1 == h2
        assert len(h1) == 16

    def test_content_hash_differs_by_message(self):
        ad1 = AdContent(id="x", title="T", message="Hello")
        ad2 = AdContent(id="x", title="T", message="World")
        assert ad1.content_hash != ad2.content_hash


class TestContentManager:
    def test_loads_ads_from_manifest(self, manager, sample_ads):
        all_ads = manager.get_all_ads()
        assert len(all_ads) == len(sample_ads)

    def test_get_active_ads_filters_inactive(self, manager):
        active = manager.get_active_ads()
        assert all(a.is_active for a in active)
        assert not any(a.id == "ad-inactive" for a in active)

    def test_get_ad_for_date_exact_match(self, manager):
        ad = manager.get_ad_for_date(date(2026, 12, 25))
        assert ad is not None
        assert ad.id == "ad-003"
        assert ad.title == "Holiday Ad"

    def test_get_ad_for_date_rotation(self, manager):
        # For a date with no exact match, should pick from general pool
        ad = manager.get_ad_for_date(date(2026, 6, 15))
        assert ad is not None
        assert ad.schedule_date is None
        assert ad.is_active is True

    def test_get_ad_for_date_rotation_varies(self, manager):
        # Two different dates should potentially give different ads
        # (depends on day-of-year mod pool size)
        ads_seen = set()
        for day in range(1, 30):
            ad = manager.get_ad_for_date(date(2026, 1, day))
            if ad:
                ads_seen.add(ad.id)
        # With 2 general pool ads, we should see at least 2 different ones
        assert len(ads_seen) >= 2

    def test_get_ad_for_date_no_active(self, tmp_path):
        # All inactive
        d = str(tmp_path / "inactive_content")
        os.makedirs(d, exist_ok=True)
        manifest = os.path.join(d, "manifest.json")
        with open(manifest, "w") as f:
            json.dump(
                {"ads": [{"id": "x", "title": "X", "is_active": False}]}, f
            )
        mgr = ContentManager(d)
        assert mgr.get_ad_for_date(date(2026, 1, 1)) is None

    def test_add_ad(self, manager):
        new_ad = AdContent(id="ad-new", title="New", message="Hello")
        manager.add_ad(new_ad)
        assert manager.get_ad_by_id("ad-new") is not None

    def test_add_duplicate_raises(self, manager):
        dup = AdContent(id="ad-001", title="Dup")
        with pytest.raises(ValueError, match="already exists"):
            manager.add_ad(dup)

    def test_update_ad(self, manager):
        updated = manager.update_ad("ad-001", {"message": "Updated!"})
        assert updated is not None
        assert updated.message == "Updated!"

    def test_delete_ad(self, manager):
        assert manager.delete_ad("ad-001") is True
        assert manager.get_ad_by_id("ad-001") is None

    def test_delete_nonexistent(self, manager):
        assert manager.delete_ad("no-such-id") is False

    def test_hot_swap_reload(self, manager, content_dir):
        # Externally modify the manifest
        manifest = os.path.join(content_dir, "manifest.json")
        with open(manifest, "w") as f:
            json.dump(
                {
                    "ads": [
                        {"id": "hot-01", "title": "Hot", "message": "Swapped", "is_active": True}
                    ]
                },
                f,
            )
        # Force mtime change
        import time
        time.sleep(0.05)
        os.utime(manifest, None)

        # check_for_updates should detect the change
        manager.check_for_updates()
        all_ads = manager.get_all_ads()
        assert len(all_ads) == 1
        assert all_ads[0].id == "hot-01"

    def test_resolve_media_path_exists(self, manager, content_dir):
        # Create a dummy media file
        media = os.path.join(content_dir, "poster.jpg")
        with open(media, "w") as f:
            f.write("fake")
        ad = manager.get_ad_by_id("ad-002")
        resolved = manager.resolve_media_path(ad)
        assert resolved is not None
        assert os.path.isfile(resolved)

    def test_resolve_media_path_missing(self, manager):
        ad = manager.get_ad_by_id("ad-002")
        # poster.jpg doesn't actually exist in tmp dir
        resolved = manager.resolve_media_path(ad)
        assert resolved is None

    def test_empty_manifest_creation(self, tmp_path):
        empty_dir = str(tmp_path / "empty_content")
        mgr = ContentManager(empty_dir)
        assert mgr.get_all_ads() == []
        assert os.path.exists(mgr.manifest_path)
