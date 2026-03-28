"""
Unit tests for the MessageSender and AutomationConfig modules.

Covers:
- AutomationConfig validation
- MessageSender state machine (reset, pause, resume, stop)
- Progress tracking accuracy
- get_results_summary pending count
- FloodWaitError retry-after-wait behaviour
- is_sending flag not leaked on early validation failure (main.py)
- _prepare_message template substitution
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import pytest

from backend.group_scanner import Group
from backend.message_sender import (
    AutomationConfig,
    MessageSender,
    SendStatus,
)


# ─────────────────────────── helpers ───────────────────────────

def _make_group(group_id: int = 1, name: str = "Test Group") -> Group:
    return Group(
        id=group_id,
        name=name,
        username=None,
        last_message_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
        member_count=10,
        is_active=False,
        access_hash=12345,
        entity_type="channel",
    )


def _make_config(**kwargs) -> AutomationConfig:
    defaults = dict(message_template="Hello {group_name}", delay_min=1, delay_max=1, max_messages=10)
    defaults.update(kwargs)
    return AutomationConfig(**defaults)


def _make_flood_wait(seconds: int):
    """Create a FloodWaitError without invoking the complex Telethon RPC constructor."""
    from telethon.errors import FloodWaitError
    err = FloodWaitError.__new__(FloodWaitError)
    err.seconds = seconds
    return err


# ─────────────────────── AutomationConfig ───────────────────────

class TestAutomationConfig:
    def test_valid_config(self):
        cfg = _make_config()
        assert cfg.validate() is True

    def test_empty_message_invalid(self):
        cfg = _make_config(message_template="")
        assert cfg.validate() is False

    def test_whitespace_only_message_invalid(self):
        cfg = _make_config(message_template="   ")
        assert cfg.validate() is False

    def test_delay_min_zero_invalid(self):
        cfg = _make_config(delay_min=0)
        assert cfg.validate() is False

    def test_delay_max_less_than_min_invalid(self):
        cfg = _make_config(delay_min=10, delay_max=5)
        assert cfg.validate() is False

    def test_max_messages_zero_invalid(self):
        cfg = _make_config(max_messages=0)
        assert cfg.validate() is False

    def test_random_delay_in_range(self):
        cfg = _make_config(delay_min=2, delay_max=5)
        for _ in range(20):
            d = cfg.get_random_delay()
            assert 2 <= d <= 5


# ─────────────────────── MessageSender state ───────────────────────

class TestMessageSenderState:
    def setup_method(self):
        self.sender = MessageSender()

    def test_initial_state(self):
        assert self.sender.is_running is False
        assert self.sender.is_paused is False
        assert self.sender.sent_count == 0
        assert self.sender.failed_count == 0
        assert self.sender.progress == 0.0

    def test_pause_resume(self):
        self.sender.pause()
        assert self.sender.is_paused is True
        self.sender.resume()
        assert self.sender.is_paused is False

    def test_stop_sets_flag(self):
        self.sender.stop()
        assert self.sender._should_stop is True

    def test_reset_clears_all(self):
        self.sender._is_running = True
        self.sender._sent_count = 5
        self.sender._failed_count = 2
        self.sender._total_groups = 10
        self.sender._results = [MagicMock()]
        self.sender._should_stop = True
        self.sender.reset()
        assert self.sender._is_running is False
        assert self.sender._sent_count == 0
        assert self.sender._failed_count == 0
        assert self.sender._total_groups == 0
        assert self.sender._results == []
        assert self.sender._should_stop is False


# ─────────────────────── progress & summary ───────────────────────

class TestProgressAndSummary:
    def setup_method(self):
        self.sender = MessageSender()

    def test_progress_zero_when_no_total(self):
        assert self.sender.progress == 0.0

    def test_progress_reflects_processed_fraction(self):
        self.sender._total_groups = 4
        self.sender._results = [MagicMock(), MagicMock()]  # 2 of 4 done
        assert self.sender.progress == pytest.approx(0.5)

    def test_progress_full_when_all_processed(self):
        self.sender._total_groups = 3
        self.sender._results = [MagicMock(), MagicMock(), MagicMock()]
        assert self.sender.progress == pytest.approx(1.0)

    def test_summary_pending_count(self):
        self.sender._total_groups = 5
        self.sender._sent_count = 2
        self.sender._failed_count = 1
        self.sender._results = [MagicMock()] * 3  # 3 processed
        summary = self.sender.get_results_summary()
        assert summary['total'] == 5
        assert summary['sent'] == 2
        assert summary['failed'] == 1
        assert summary['pending'] == 2  # 5 - 3 processed

    def test_summary_pending_never_negative(self):
        self.sender._total_groups = 2
        self.sender._results = [MagicMock()] * 5  # more results than total (edge case)
        summary = self.sender.get_results_summary()
        assert summary['pending'] == 0


# ─────────────────────── _prepare_message ───────────────────────

class TestPrepareMessage:
    def setup_method(self):
        self.sender = MessageSender()

    def test_group_name_substitution(self):
        group = _make_group(name="Alpha")
        result = self.sender._prepare_message("Hi {group_name}!", group)
        assert result == "Hi Alpha!"

    def test_group_id_substitution(self):
        group = _make_group(group_id=999)
        result = self.sender._prepare_message("ID: {group_id}", group)
        assert result == "ID: 999"

    def test_last_message_substitution_with_time(self):
        group = _make_group()
        group.last_message_time = datetime(2026, 3, 15, 10, 30, tzinfo=timezone.utc)
        result = self.sender._prepare_message("Last: {last_message}", group)
        assert result == "Last: 2026-03-15 10:30"

    def test_last_message_substitution_no_time(self):
        group = _make_group()
        group.last_message_time = None
        result = self.sender._prepare_message("Last: {last_message}", group)
        assert result == "Last: Unknown"

    def test_no_substitution_needed(self):
        group = _make_group()
        result = self.sender._prepare_message("Static message", group)
        assert result == "Static message"


# ─────────────────────── send_messages async ───────────────────────

@pytest.fixture
def mock_client_manager():
    with patch("backend.message_sender.client_manager") as mock_cm:
        mock_cm.is_authenticated = True
        mock_cm.client = MagicMock()
        mock_cm.client.send_message = AsyncMock()
        mock_cm.client.get_input_entity = AsyncMock(side_effect=ValueError("not cached"))
        yield mock_cm


class TestSendMessages:
    def setup_method(self):
        self.sender = MessageSender()

    async def test_raises_if_not_authenticated(self):
        with patch("backend.message_sender.client_manager") as mock_cm:
            mock_cm.is_authenticated = False
            with pytest.raises(RuntimeError, match="not authenticated"):
                await self.sender.send_messages([_make_group()], _make_config())

    async def test_raises_if_config_invalid(self, mock_client_manager):
        bad_cfg = _make_config(message_template="")
        with pytest.raises(ValueError, match="Invalid"):
            await self.sender.send_messages([_make_group()], bad_cfg)

    async def test_successful_send(self, mock_client_manager):
        groups = [_make_group(i, f"Group {i}") for i in range(3)]
        cfg = _make_config(delay_min=1, delay_max=1)
        results = await self.sender.send_messages(groups, cfg)
        assert len(results) == 3
        assert all(r.status == SendStatus.SENT for r in results)
        assert self.sender.sent_count == 3
        assert self.sender.failed_count == 0
        assert self.sender.progress == pytest.approx(1.0)

    async def test_dry_run_does_not_call_send(self, mock_client_manager):
        groups = [_make_group()]
        cfg = _make_config(dry_run=True, delay_min=1, delay_max=1)
        results = await self.sender.send_messages(groups, cfg)
        mock_client_manager.client.send_message.assert_not_called()
        assert results[0].status == SendStatus.SENT

    async def test_stop_mid_run(self, mock_client_manager):
        groups = [_make_group(i, f"Group {i}") for i in range(10)]
        cfg = _make_config(delay_min=1, delay_max=1)

        call_count = 0

        async def send_and_stop(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                self.sender.stop()

        mock_client_manager.client.send_message = send_and_stop
        results = await self.sender.send_messages(groups, cfg)
        assert len(results) < 10

    async def test_is_running_false_after_completion(self, mock_client_manager):
        groups = [_make_group()]
        cfg = _make_config(delay_min=1, delay_max=1)
        await self.sender.send_messages(groups, cfg)
        assert self.sender.is_running is False

    async def test_total_groups_capped_by_max_messages(self, mock_client_manager):
        groups = [_make_group(i, f"G{i}") for i in range(10)]
        cfg = _make_config(max_messages=3, delay_min=1, delay_max=1)
        results = await self.sender.send_messages(groups, cfg)
        assert len(results) == 3
        assert self.sender._total_groups == 3

    async def test_send_failure_increments_failed_count(self, mock_client_manager):
        mock_client_manager.client.send_message = AsyncMock(side_effect=Exception("network error"))
        groups = [_make_group()]
        cfg = _make_config(delay_min=1, delay_max=1)
        results = await self.sender.send_messages(groups, cfg)
        assert results[0].status == SendStatus.FAILED
        assert self.sender.failed_count == 1


# ─────────────────────── FloodWaitError retry ───────────────────────

class TestFloodWaitRetry:
    def setup_method(self):
        self.sender = MessageSender()

    async def test_flood_wait_retries_and_succeeds(self, mock_client_manager):
        flood = _make_flood_wait(seconds=0)
        call_count = 0

        async def send_side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise flood

        mock_client_manager.client.send_message = send_side_effect

        group = _make_group()
        group.entity_type = "chat"
        result = await self.sender._send_single_message(group, "hello")
        assert result.status == SendStatus.SENT
        assert call_count == 2  # first attempt + retry

    async def test_flood_wait_retry_fails_returns_failed(self, mock_client_manager):
        flood = _make_flood_wait(seconds=0)

        async def always_flood(*args, **kwargs):
            raise flood

        mock_client_manager.client.send_message = always_flood

        group = _make_group()
        group.entity_type = "chat"
        result = await self.sender._send_single_message(group, "hello")
        assert result.status == SendStatus.FAILED

    async def test_flood_wait_during_stop_skips_retry(self, mock_client_manager):
        flood = _make_flood_wait(seconds=0)
        self.sender._should_stop = True
        call_count = 0

        async def raise_flood(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            raise flood

        mock_client_manager.client.send_message = raise_flood

        group = _make_group()
        group.entity_type = "chat"
        result = await self.sender._send_single_message(group, "hello")
        assert result.status == SendStatus.RATE_LIMITED
        # Retry must not have been attempted — stop flag was set
        assert call_count == 1


# ─────────────────────── is_sending flag leak (main.py) ───────────────────────

class TestIsSendingFlagLeak:
    """
    Verifies that /api/automation/send does NOT leave app_state.is_sending=True
    when validation fails (BUG-004 fix). Uses Flask test client.
    """

    @pytest.fixture(autouse=True)
    def _setup_app(self):
        import main as app_module
        self.app = app_module.app
        self.app_state = app_module.app_state
        self.app_state_lock = app_module.app_state_lock

        # Patch is_authenticated via the underlying private attribute
        app_module.client_manager._is_authenticated = True
        self.test_client = self.app.test_client()
        yield
        # Reset state between tests
        app_module.client_manager._is_authenticated = False
        with self.app_state_lock:
            self.app_state.is_sending = False

    def test_empty_message_does_not_lock_is_sending(self):
        resp = self.test_client.post(
            "/api/automation/send",
            json={"message": "   ", "target": "all"},
        )
        assert resp.status_code == 400
        with self.app_state_lock:
            assert self.app_state.is_sending is False

    def test_no_groups_does_not_lock_is_sending(self):
        original_groups = self.app_state.groups
        self.app_state.groups = []
        resp = self.test_client.post(
            "/api/automation/send",
            json={"message": "Hello", "target": "all"},
        )
        self.app_state.groups = original_groups
        assert resp.status_code == 400
        with self.app_state_lock:
            assert self.app_state.is_sending is False

    def test_second_send_blocked_while_running(self):
        """Once is_sending is True, a second request must return 400."""
        with self.app_state_lock:
            self.app_state.is_sending = True
        resp = self.test_client.post(
            "/api/automation/send",
            json={"message": "Hello", "target": "all"},
        )
        assert resp.status_code == 400
        data = resp.get_json()
        assert "progress" in data or "error" in data
