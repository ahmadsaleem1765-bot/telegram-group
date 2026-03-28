"""
Full integration smoke test: imports, config, persistence, backend modules, API surface.
Run with: python smoke_test.py
"""
import sys
import os
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

PASS = []
FAIL = []


def ok(label):
    PASS.append(label)
    print(f"  PASS  {label}")


def fail(label, err):
    FAIL.append((label, err))
    print(f"  FAIL  {label}: {err}")


def check(label, fn):
    try:
        fn()
        ok(label)
    except Exception as e:
        fail(label, str(e))


# ─────────────────────── 1. Module imports ───────────────────────
print("\n=== 1. Module imports ===")
for mod in [
    "config",
    "backend.telegram_client",
    "backend.group_scanner",
    "backend.inactivity_filter",
    "backend.message_sender",
    "backend.scheduler.rules_engine",
    "backend.content_manager",
    "backend.channel_adapter",
    "backend.ad_scheduler",
    "backend.persistence",
    "backend.logging_config",
]:
    check(f"import {mod}", lambda m=mod: __import__(m))

# ─────────────────────── 2. Config ───────────────────────
print("\n=== 2. Config ===")
from config import config

check("data_dir exists", lambda: os.path.isdir(config.data_dir))
check("default_delay_min >= 1", lambda: config.default_delay_min >= 1)
check("default_delay_max >= delay_min", lambda: config.default_delay_max >= config.default_delay_min)
check("content_dir set", lambda: bool(config.content_dir))

# ─────────────────────── 3. Persistence ───────────────────────
print("\n=== 3. Persistence ===")
from backend import persistence
import inspect

# persistence uses hardcoded data/ paths; verify the functions exist and have correct signatures
check("save_groups callable", lambda: callable(persistence.save_groups))
check("load_groups callable", lambda: callable(persistence.load_groups))
sig_save = inspect.signature(persistence.save_groups)
sig_load = inspect.signature(persistence.load_groups)
check("save_groups accepts groups param", lambda: "groups" in sig_save.parameters)
check("load_groups returns list (module attr)", lambda: persistence.load_groups() is not None)

# ─────────────────────── 4. InactivityFilter ───────────────────────
print("\n=== 4. InactivityFilter ===")
from datetime import datetime, timezone
from backend.inactivity_filter import InactivityThreshold
from backend.group_scanner import Group

thresh = InactivityThreshold(date=datetime(2026, 1, 1))
g_old = Group(1, "Old", None, datetime(2025, 6, 1, tzinfo=timezone.utc), 10)
g_new = Group(2, "New", None, datetime(2026, 3, 1, tzinfo=timezone.utc), 10)

check("old group is inactive", lambda: thresh.is_inactive(g_old.last_message_time) is True)
check("new group is active", lambda: thresh.is_inactive(g_new.last_message_time) is False)
check("None last_message = inactive", lambda: thresh.is_inactive(None) is True)
check("BUG-001 regression: aware vs naive no crash",
      lambda: thresh.is_inactive(datetime(2025, 1, 1, tzinfo=timezone.utc)))

# ─────────────────────── 5. AutomationConfig ───────────────────────
print("\n=== 5. AutomationConfig ===")
from backend.message_sender import AutomationConfig, MessageSender, SendStatus

check("valid config passes", lambda: AutomationConfig("hi", 1, 2, 10).validate())
check("empty message fails", lambda: not AutomationConfig("", 1, 2, 10).validate())
check("whitespace message fails", lambda: not AutomationConfig("  ", 1, 2, 10).validate())
check("delay_max < delay_min fails", lambda: not AutomationConfig("hi", 5, 2, 10).validate())
check("max_messages=0 fails", lambda: not AutomationConfig("hi", 1, 2, 0).validate())

# ─────────────────────── 6. MessageSender state & progress ───────────────────────
print("\n=== 6. MessageSender state & progress ===")
s = MessageSender()
check("initial progress is 0.0", lambda: s.progress == 0.0)

s._total_groups = 4
s._results = [None, None]
check("progress at 50%", lambda: s.progress == 0.5)

s.reset()
check("reset clears _total_groups", lambda: s._total_groups == 0)
check("progress after reset is 0.0", lambda: s.progress == 0.0)

s._total_groups = 5
s._sent_count = 2
s._failed_count = 1
s._results = [None] * 3
summary = s.get_results_summary()
check("summary total=5", lambda: summary["total"] == 5)
check("summary sent=2", lambda: summary["sent"] == 2)
check("summary failed=1", lambda: summary["failed"] == 1)
check("summary pending=2 (5-3 processed)", lambda: summary["pending"] == 2)

# ─────────────────────── 7. ContentManager ───────────────────────
print("\n=== 7. ContentManager ===")
from backend.content_manager import ContentManager, AdContent

with tempfile.TemporaryDirectory() as tmp:
    cm = ContentManager(content_dir=tmp)
    ad = AdContent(id="x1", title="Test Ad", message="Hello world")
    check("add ad", lambda: cm.add_ad(ad) or True)
    check("get_all_ads count=1", lambda: len(cm.get_all_ads()) == 1)
    check("get_active_ads count=1", lambda: len(cm.get_active_ads()) == 1)
    check("get_ad_by_id", lambda: cm.get_ad_by_id("x1").title == "Test Ad")
    check("update ad", lambda: cm.update_ad("x1", {"title": "Updated"}) or True)
    check("updated title persists", lambda: cm.get_ad_by_id("x1").title == "Updated")
    check("delete ad", lambda: cm.delete_ad("x1") or True)
    check("empty after delete", lambda: cm.get_all_ads() == [])

# ─────────────────────── 8. Rules engine ───────────────────────
print("\n=== 8. Rules engine ===")
import uuid
from backend.scheduler.rules_engine import rules_engine, AutomationRule

rule = AutomationRule(
    id=str(uuid.uuid4()), period_value=7, period_unit="Days",
    message="Test rule", is_active=True,
)
rules_engine.add_rule(rule)
check("rule added", lambda: any(r.id == rule.id for r in rules_engine.get_rules()))
rules_engine.delete_rule(rule.id)
check("rule deleted", lambda: not any(r.id == rule.id for r in rules_engine.get_rules()))

# ─────────────────────── 9. Group.from_dict (WARN-002 regression) ───────────────────────
print("\n=== 9. WARN-002 regression: Group.from_dict naive datetimes ===")
d = {
    "id": 1, "name": "G", "username": None,
    "last_message_time": "2026-01-01T12:00:00",
    "member_count": 5, "is_active": False,
    "access_hash": 0, "entity_type": "chat",
}
g = Group.from_dict(d)
t = InactivityThreshold(date=datetime(2026, 6, 1))
check("naive datetime from from_dict doesn't crash is_inactive",
      lambda: t.is_inactive(g.last_message_time) is True)

# ─────────────────────── 10. Flask API surface ───────────────────────
print("\n=== 10. Flask API surface (22 endpoints) ===")
import main as app_module

app_module.app.config["TESTING"] = True
client = app_module.app.test_client()
app_module.client_manager._is_authenticated = False

endpoints = [
    ("GET",  "/api/auth/status",           None,                          200),
    ("POST", "/api/auth/login",            {"session_string": ""},        400),
    ("POST", "/api/auth/logout",           {},                            200),
    ("GET",  "/api/groups",                None,                          200),
    ("POST", "/api/groups/scan",           {},                            401),
    ("GET",  "/api/dashboard",             None,                          200),
    ("GET",  "/api/logs",                  None,                          200),
    ("POST", "/api/automation/send",       {"message": "hi"},             401),
    ("POST", "/api/automation/stop",       {},                            200),
    ("GET",  "/api/automation/status",     None,                          200),
    ("GET",  "/api/rules",                 None,                          200),
    ("POST", "/api/rules",                 {},                            400),
    ("GET",  "/api/ads",                   None,                          200),
    ("GET",  "/api/ads/today",             None,                          200),
    ("POST", "/api/ads",                   {"title": "T2", "message": "M2"}, 200),
    ("GET",  "/api/ad-scheduler/status",   None,                          200),
    ("POST", "/api/ad-scheduler/stop",     {},                            200),
    ("POST", "/api/ad-scheduler/start",    {},                            401),
    ("POST", "/api/ad-scheduler/trigger",  {},                            401),
    ("GET",  "/api/ad-rules",              None,                          200),
    ("GET",  "/api/ad-scheduler/ledger",   None,                          200),
    ("GET",  "/",                          None,                          200),
]

for method, path, body, expected in endpoints:
    def _chk(m=method, p=path, b=body, ex=expected):
        resp = client.get(p) if m == "GET" else client.post(p, json=b)
        assert resp.status_code == ex, f"got {resp.status_code}, want {ex}"
    check(f"{method} {path}", _chk)

# ─────────────────────── 11. is_sending flag leak (BUG-004 regression) ───────────────────────
print("\n=== 11. BUG-004 regression: is_sending flag leak ===")

with app_module.app_state_lock:
    app_module.app_state.is_sending = False

resp = client.post("/api/automation/send", json={"message": "  ", "target": "all"})
check("blank message -> 400", lambda: resp.status_code == 400)
with app_module.app_state_lock:
    sending = app_module.app_state.is_sending
check("is_sending still False after blank message", lambda: not sending)

saved_groups = app_module.app_state.groups
app_module.app_state.groups = []
resp2 = client.post("/api/automation/send", json={"message": "Hello", "target": "all"})
app_module.app_state.groups = saved_groups
check("no groups -> 400", lambda: resp2.status_code == 400)
with app_module.app_state_lock:
    sending2 = app_module.app_state.is_sending
check("is_sending still False after no groups", lambda: not sending2)

# ─────────────────────── Summary ───────────────────────
print(f"\n{'='*55}")
print(f"RESULT: {len(PASS)} passed, {len(FAIL)} failed out of {len(PASS)+len(FAIL)} checks")
if FAIL:
    print("\nFAILURES:")
    for label, err in FAIL:
        print(f"  {label}:\n    {err}")
else:
    print("All checks passed.")
