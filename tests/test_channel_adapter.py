"""
Unit tests for the Channel Adapter module.

Tests the DeliveryEngine retry logic, exponential backoff,
and adapter registration. Uses mock adapters to avoid external dependencies.
"""

import pytest

from backend.channel_adapter import (
    ChannelAdapter,
    DeliveryEngine,
    DeliveryStatus,
    Destination,
)


class MockAdapter(ChannelAdapter):
    """Mock adapter for testing."""

    def __init__(self, should_fail: int = 0):
        self._fail_count = should_fail
        self._call_count = 0
        self.sent_messages = []

    @property
    def adapter_type(self) -> str:
        return "mock"

    async def send_text(self, destination_id: str, text: str) -> None:
        self._call_count += 1
        if self._call_count <= self._fail_count:
            raise ConnectionError(f"Simulated failure #{self._call_count}")
        self.sent_messages.append({"dest": destination_id, "text": text})

    async def send_media(
        self, destination_id, media_path, media_type, caption=None
    ):
        self._call_count += 1
        if self._call_count <= self._fail_count:
            raise ConnectionError(f"Simulated failure #{self._call_count}")
        self.sent_messages.append(
            {
                "dest": destination_id,
                "media": media_path,
                "type": media_type,
                "caption": caption,
            }
        )

    async def is_available(self) -> bool:
        return True


@pytest.fixture
def engine():
    return DeliveryEngine(
        max_retries=3,
        backoff_base=0.01,  # Very short for tests
        backoff_cap=0.1,
        inter_send_delay=0.01,
    )


@pytest.fixture
def destination():
    return Destination(id="123", name="Test Group", type="mock")


class TestDeliveryEngine:
    @pytest.mark.asyncio
    async def test_successful_delivery(self, engine, destination):
        adapter = MockAdapter(should_fail=0)
        engine.register_adapter(adapter)
        result = await engine.deliver(
            destination, content_id="ad-1", text="Hello"
        )
        assert result.status == DeliveryStatus.SUCCESS
        assert result.attempts == 1
        assert len(adapter.sent_messages) == 1

    @pytest.mark.asyncio
    async def test_retry_then_success(self, engine, destination):
        adapter = MockAdapter(should_fail=2)
        engine.register_adapter(adapter)
        result = await engine.deliver(
            destination, content_id="ad-1", text="Hello"
        )
        assert result.status == DeliveryStatus.SUCCESS
        assert result.attempts == 3  # 2 failures + 1 success

    @pytest.mark.asyncio
    async def test_all_retries_exhausted(self, engine, destination):
        adapter = MockAdapter(should_fail=10)  # More than max_retries+1
        engine.register_adapter(adapter)
        result = await engine.deliver(
            destination, content_id="ad-1", text="Hello"
        )
        assert result.status == DeliveryStatus.FAILED
        assert result.attempts == 4  # 1 initial + 3 retries
        assert "Simulated failure" in result.error

    @pytest.mark.asyncio
    async def test_no_adapter_skips(self, engine):
        dest = Destination(id="1", name="X", type="unknown")
        result = await engine.deliver(dest, content_id="ad-1", text="Hi")
        assert result.status == DeliveryStatus.SKIPPED
        assert "No adapter" in result.error

    @pytest.mark.asyncio
    async def test_no_content_skips(self, engine, destination):
        adapter = MockAdapter()
        engine.register_adapter(adapter)
        result = await engine.deliver(destination, content_id="ad-1")
        assert result.status == DeliveryStatus.SKIPPED

    @pytest.mark.asyncio
    async def test_media_delivery(self, engine, destination):
        adapter = MockAdapter()
        engine.register_adapter(adapter)
        result = await engine.deliver(
            destination,
            content_id="ad-1",
            media_path="/tmp/poster.jpg",
            media_type="photo",
            text="Check this out!",
        )
        assert result.status == DeliveryStatus.SUCCESS
        assert adapter.sent_messages[0]["media"] == "/tmp/poster.jpg"

    @pytest.mark.asyncio
    async def test_deliver_to_many(self, engine):
        adapter = MockAdapter()
        engine.register_adapter(adapter)
        destinations = [
            Destination(id=str(i), name=f"Group {i}", type="mock")
            for i in range(3)
        ]
        results = await engine.deliver_to_many(
            destinations, content_id="ad-1", text="Broadcast"
        )
        assert len(results) == 3
        assert all(r.status == DeliveryStatus.SUCCESS for r in results)

    def test_backoff_calculation(self, engine):
        assert engine._calculate_backoff(0) == pytest.approx(0.01, abs=0.001)
        assert engine._calculate_backoff(1) == pytest.approx(0.02, abs=0.001)
        assert engine._calculate_backoff(2) == pytest.approx(0.04, abs=0.001)
        # Should be capped at 0.1
        assert engine._calculate_backoff(10) == pytest.approx(0.1, abs=0.001)

    def test_register_adapter(self, engine):
        adapter = MockAdapter()
        engine.register_adapter(adapter)
        assert engine.get_adapter("mock") is adapter
        assert engine.get_adapter("nonexistent") is None
