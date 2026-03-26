"""
Flask API tests for the Ads and Ad Scheduler endpoints.

Tests cover CRUD for ad content and scheduler start/stop/trigger via
the Flask test client. No real Telegram connection is required.
"""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def app(tmp_path, monkeypatch):
    """Create a Flask test app with fully isolated content_manager and app_state."""
    import unittest.mock as mock
    import importlib

    content_dir = str(tmp_path / "content")
    ledger_path = str(tmp_path / "ledger.json")

    with mock.patch("telethon.TelegramClient"):
        import main as app_module
        importlib.reload(app_module)
        flask_app = app_module.app

    # Replace global content_manager with a fresh one pointing at tmp_path
    from backend.content_manager import ContentManager
    from backend.ad_scheduler import AdScheduler, DeliveryLedger
    from backend.channel_adapter import DeliveryEngine

    fresh_cm = ContentManager(content_dir)
    fresh_ledger = DeliveryLedger(ledger_path)
    fresh_engine = DeliveryEngine()
    fresh_scheduler = AdScheduler(
        content_manager=fresh_cm,
        delivery_engine=fresh_engine,
        ledger=fresh_ledger,
    )

    monkeypatch.setattr(app_module, "content_manager", fresh_cm)
    monkeypatch.setattr(app_module, "ad_scheduler", fresh_scheduler)

    flask_app.config["TESTING"] = True
    yield flask_app


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def json_headers():
    return {"Content-Type": "application/json"}


# ---------------------------------------------------------------------------
# /api/ads  —  CRUD
# ---------------------------------------------------------------------------


class TestAdsEndpoints:
    def test_get_ads_empty(self, client):
        res = client.get("/api/ads")
        assert res.status_code == 200
        data = res.get_json()
        assert "ads" in data
        assert isinstance(data["ads"], list)

    def test_create_ad(self, client, json_headers):
        payload = {"title": "My Ad", "message": "Hello world", "is_active": True}
        res = client.post("/api/ads", data=json.dumps(payload), headers=json_headers)
        assert res.status_code == 200
        data = res.get_json()
        assert data["success"] is True
        assert data["ad"]["title"] == "My Ad"
        assert data["ad"]["id"]  # auto-generated id

    def test_create_ad_persists(self, client, json_headers):
        payload = {"title": "Persistent", "message": "Test"}
        client.post("/api/ads", data=json.dumps(payload), headers=json_headers)

        res = client.get("/api/ads")
        ads = res.get_json()["ads"]
        titles = [a["title"] for a in ads]
        assert "Persistent" in titles

    def test_create_multiple_ads(self, client, json_headers):
        for i in range(3):
            client.post(
                "/api/ads",
                data=json.dumps({"title": f"Ad {i}", "message": f"Msg {i}"}),
                headers=json_headers,
            )
        res = client.get("/api/ads")
        assert res.get_json()["count"] == 3

    def test_update_ad(self, client, json_headers):
        # Create
        created = client.post(
            "/api/ads",
            data=json.dumps({"title": "Original", "message": "Old"}),
            headers=json_headers,
        ).get_json()
        ad_id = created["ad"]["id"]

        # Update
        res = client.put(
            f"/api/ads/{ad_id}",
            data=json.dumps({"message": "Updated!"}),
            headers=json_headers,
        )
        assert res.status_code == 200
        assert res.get_json()["ad"]["message"] == "Updated!"

    def test_update_nonexistent_ad(self, client, json_headers):
        res = client.put(
            "/api/ads/no-such-id",
            data=json.dumps({"message": "x"}),
            headers=json_headers,
        )
        assert res.status_code == 404

    def test_delete_ad(self, client, json_headers):
        created = client.post(
            "/api/ads",
            data=json.dumps({"title": "ToDelete", "message": "bye"}),
            headers=json_headers,
        ).get_json()
        ad_id = created["ad"]["id"]

        res = client.delete(f"/api/ads/{ad_id}")
        assert res.status_code == 200
        assert res.get_json()["success"] is True

        # Confirm gone
        ads = client.get("/api/ads").get_json()["ads"]
        assert not any(a["id"] == ad_id for a in ads)

    def test_delete_nonexistent_ad(self, client):
        res = client.delete("/api/ads/ghost-id")
        assert res.status_code == 404

    def test_get_todays_ad_no_ads(self, client):
        res = client.get("/api/ads/today")
        assert res.status_code == 200
        data = res.get_json()
        assert data["ad"] is None

    def test_get_todays_ad_with_active_ad(self, client, json_headers):
        client.post(
            "/api/ads",
            data=json.dumps({"title": "Daily", "message": "Today's message", "is_active": True}),
            headers=json_headers,
        )
        res = client.get("/api/ads/today")
        assert res.status_code == 200
        ad = res.get_json()["ad"]
        assert ad is not None
        assert ad["title"] == "Daily"

    def test_get_todays_ad_inactive_returns_none(self, client, json_headers):
        client.post(
            "/api/ads",
            data=json.dumps({"title": "Inactive", "message": "x", "is_active": False}),
            headers=json_headers,
        )
        res = client.get("/api/ads/today")
        assert res.get_json()["ad"] is None

    def test_create_ad_with_schedule_date(self, client, json_headers):
        payload = {
            "title": "Dated Ad",
            "message": "Only on New Year",
            "schedule_date": "2026-01-01",
            "is_active": True,
        }
        res = client.post("/api/ads", data=json.dumps(payload), headers=json_headers)
        assert res.status_code == 200
        assert res.get_json()["ad"]["schedule_date"] == "2026-01-01"

    def test_csrf_requires_json_content_type(self, client):
        """POST without application/json should be rejected."""
        res = client.post(
            "/api/ads",
            data="title=bad",
            content_type="application/x-www-form-urlencoded",
        )
        assert res.status_code == 415


# ---------------------------------------------------------------------------
# /api/ad-scheduler  —  status, start, stop
# ---------------------------------------------------------------------------


class TestAdSchedulerEndpoints:
    def test_scheduler_status_initially_stopped(self, client):
        res = client.get("/api/ad-scheduler/status")
        assert res.status_code == 200
        data = res.get_json()
        assert data["is_running"] is False

    def test_start_scheduler_requires_auth(self, client, json_headers):
        """Should fail when not authenticated."""
        res = client.post(
            "/api/ad-scheduler/start",
            data=json.dumps({"schedule_time": "09:00", "timezone": "UTC"}),
            headers=json_headers,
        )
        # Not authenticated → 401
        assert res.status_code == 401

    def test_stop_scheduler_when_not_running(self, client, json_headers):
        res = client.post(
            "/api/ad-scheduler/stop",
            data=json.dumps({}),
            headers=json_headers,
        )
        # Should succeed gracefully even if not running
        assert res.status_code == 200

    def test_trigger_requires_auth(self, client, json_headers):
        res = client.post(
            "/api/ad-scheduler/trigger",
            data=json.dumps({}),
            headers=json_headers,
        )
        assert res.status_code == 401

    def test_scheduler_status_keys(self, client):
        data = client.get("/api/ad-scheduler/status").get_json()
        for key in ("is_running", "schedule_time", "timezone", "last_run", "destinations_count"):
            assert key in data, f"Missing key: {key}"
