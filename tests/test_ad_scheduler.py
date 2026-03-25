"""
Unit and integration tests for the Ad Scheduler module.

Tests idempotency via DeliveryLedger, daily delivery flow,
and scheduler lifecycle. Uses mock adapters and temporary files.
"""

import json
import os
from datetime import date

import pytest

from backend.ad_scheduler import AdScheduler, DeliveryLedger
from backend.channel_adapter import (
    DeliveryEngine,
    DeliveryStatus,
    Destination,
)
from backend.content_manager import ContentManager


# ==================== DeliveryLedger Tests ====================


@pytest.fixture
def ledger_path(tmp_path):
    return str(tmp_path / "ledger.json")


@pytest.fixture
def ledger(ledger_path):
    return DeliveryLedger(ledger_path)


class TestDeliveryLedger:
    def test_empty_ledger(self, ledger):
        records = ledger.get_records_for_date(date(2026, 3, 25))
        assert records == []

    def test_record_and_check(self, ledger):
        today = date(2026, 3, 25)
        ledger.record_delivery(
            content_id="ad-1",
            content_hash="abc123",
            destination_id="group-1",
            delivery_date=today,
            status=DeliveryStatus.SUCCESS,
        )
        assert ledger.was_delivered("abc123", "group-1", today)
        assert not ledger.was_delivered("abc123", "group-2", today)
        assert not ledger.was_delivered("abc123", "group-1", date(2026, 3, 26))

    def test_failed_delivery_not_counted_as_delivered(self, ledger):
        today = date(2026, 3, 25)
        ledger.record_delivery(
            content_id="ad-1",
            content_hash="abc123",
            destination_id="group-1",
            delivery_date=today,
            status=DeliveryStatus.FAILED,
        )
        assert not ledger.was_delivered("abc123", "group-1", today)

    def test_persistence_across_instances(self, ledger_path):
        today = date(2026, 3, 25)
        ledger1 = DeliveryLedger(ledger_path)
        ledger1.record_delivery(
            "ad-1", "hash1", "g1", today, DeliveryStatus.SUCCESS
        )

        # New instance from same file
        ledger2 = DeliveryLedger(ledger_path)
        assert ledger2.was_delivered("hash1", "g1", today)

    def test_prune_old_records(self, ledger):
        old = date(2026, 1, 1)
        recent = date(2026, 3, 20)
        ledger.record_delivery("ad-1", "h1", "g1", old, DeliveryStatus.SUCCESS)
        ledger.record_delivery("ad-2", "h2", "g1", recent, DeliveryStatus.SUCCESS)

        removed = ledger.prune_before(date(2026, 3, 1))
        assert removed == 1
        assert len(ledger.get_records_for_date(old)) == 0
        assert len(ledger.get_records_for_date(recent)) == 1

    def test_get_records_for_date(self, ledger):
        today = date(2026, 3, 25)
        ledger.record_delivery("ad-1", "h1", "g1", today, DeliveryStatus.SUCCESS)
        ledger.record_delivery("ad-1", "h1", "g2", today, DeliveryStatus.FAILED)
        records = ledger.get_records_for_date(today)
        assert len(records) == 2


# ==================== AdScheduler Integration Tests ====================


class MockChannelAdapter:
    """Mock adapter for integration testing."""

    def __init__(self):
        self.sent = []
        self.should_fail = False

    @property
    def adapter_type(self):
        return "mock"

    async def send_text(self, destination_id, text):
        if self.should_fail:
            raise ConnectionError("Mock failure")
        self.sent.append({"dest": destination_id, "text": text})

    async def send_media(self, destination_id, media_path, media_type, caption=None):
        if self.should_fail:
            raise ConnectionError("Mock failure")
        self.sent.append(
            {"dest": destination_id, "media": media_path, "caption": caption}
        )

    async def is_available(self):
        return True


@pytest.fixture
def content_dir(tmp_path):
    d = str(tmp_path / "content")
    os.makedirs(d, exist_ok=True)
    manifest = os.path.join(d, "manifest.json")
    with open(manifest, "w") as f:
        json.dump(
            {
                "ads": [
                    {
                        "id": "test-ad",
                        "title": "Test Ad",
                        "message": "Hello from test!",
                        "is_active": True,
                        "priority": 10,
                    }
                ]
            },
            f,
        )
    return d


@pytest.fixture
def mock_adapter():
    return MockChannelAdapter()


@pytest.fixture
def delivery_engine(mock_adapter):
    engine = DeliveryEngine(
        max_retries=1, backoff_base=0.01, backoff_cap=0.05, inter_send_delay=0.01
    )
    engine.register_adapter(mock_adapter)
    return engine


@pytest.fixture
def ad_scheduler_instance(content_dir, delivery_engine, ledger):
    cm = ContentManager(content_dir)
    return AdScheduler(
        content_manager=cm,
        delivery_engine=delivery_engine,
        ledger=ledger,
        schedule_hour=9,
        schedule_minute=0,
    )


class TestAdScheduler:
    @pytest.mark.asyncio
    async def test_daily_delivery_sends_to_destinations(
        self, ad_scheduler_instance, mock_adapter
    ):
        destinations = [
            Destination(id="1", name="Group A", type="mock"),
            Destination(id="2", name="Group B", type="mock"),
        ]
        ad_scheduler_instance.set_destinations(destinations)
        results = await ad_scheduler_instance.run_daily_delivery()
        assert len(results) == 2
        assert all(r.status == DeliveryStatus.SUCCESS for r in results)
        assert len(mock_adapter.sent) == 2

    @pytest.mark.asyncio
    async def test_idempotency_prevents_resend(
        self, ad_scheduler_instance, mock_adapter
    ):
        destinations = [
            Destination(id="1", name="Group A", type="mock"),
        ]
        ad_scheduler_instance.set_destinations(destinations)

        # First run
        results1 = await ad_scheduler_instance.run_daily_delivery()
        assert results1[0].status == DeliveryStatus.SUCCESS

        # Second run same day - should skip
        results2 = await ad_scheduler_instance.run_daily_delivery()
        assert results2[0].status == DeliveryStatus.SKIPPED
        assert len(mock_adapter.sent) == 1  # Only sent once

    @pytest.mark.asyncio
    async def test_no_active_ads_returns_empty(
        self, delivery_engine, ledger, tmp_path
    ):
        d = str(tmp_path / "empty_content")
        os.makedirs(d, exist_ok=True)
        manifest = os.path.join(d, "manifest.json")
        with open(manifest, "w") as f:
            json.dump({"ads": []}, f)

        cm = ContentManager(d)
        sched = AdScheduler(cm, delivery_engine, ledger)
        sched.set_destinations(
            [Destination(id="1", name="G", type="mock")]
        )
        results = await sched.run_daily_delivery()
        assert results == []

    @pytest.mark.asyncio
    async def test_no_destinations_returns_empty(self, ad_scheduler_instance):
        # Don't set destinations
        results = await ad_scheduler_instance.run_daily_delivery()
        assert results == []

    @pytest.mark.asyncio
    async def test_scheduler_start_stop(self, ad_scheduler_instance):
        # APScheduler's AsyncIOScheduler requires a running event loop
        ad_scheduler_instance.start()
        assert ad_scheduler_instance.is_running
        status = ad_scheduler_instance.get_status()
        assert status["is_running"] is True
        assert status["schedule_time"] == "09:00"

        ad_scheduler_instance.stop()
        assert not ad_scheduler_instance.is_running

    def test_update_schedule(self, ad_scheduler_instance):
        ad_scheduler_instance.update_schedule(14, 30, "US/Eastern")
        status = ad_scheduler_instance.get_status()
        assert status["schedule_time"] == "14:30"
        assert status["timezone"] == "US/Eastern"

    def test_get_status(self, ad_scheduler_instance):
        status = ad_scheduler_instance.get_status()
        assert "is_running" in status
        assert "schedule_time" in status
        assert "timezone" in status
        assert "last_run" in status
        assert "destinations_count" in status
