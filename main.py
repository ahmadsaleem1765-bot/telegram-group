"""
Telegram Controller Automation - Main Application

A Flask-based web application for managing Telegram group automation.
"""

import os
import json
import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field

from flask import Flask, render_template, request, jsonify, Response
from flask_cors import CORS
from telethon import events

# Setup directories
os.makedirs('logs', exist_ok=True)
os.makedirs('data', exist_ok=True)
os.makedirs('content', exist_ok=True)

# Configure structured logging
from backend.logging_config import setup_logging  # noqa: E402
setup_logging(logs_dir='logs', json_format=True)
logger = logging.getLogger(__name__)

# Import configuration
from config import config  # noqa: E402

# Import backend modules
from backend.telegram_client import client_manager, TelegramUser  # noqa: E402
from backend.group_scanner import scanner, Group  # noqa: E402
from backend.inactivity_filter import InactivityFilter  # noqa: E402
from backend.message_sender import sender, AutomationConfig, SendStatus  # noqa: E402
from backend.scheduler.rules_engine import rules_engine, AutomationRule  # noqa: E402
from backend import persistence  # noqa: E402
from backend.content_manager import ContentManager, AdContent  # noqa: E402
from backend.channel_adapter import (  # noqa: E402
    TelegramAdapter, DeliveryEngine, Destination, DeliveryStatus,
)
from backend.ad_scheduler import AdScheduler, DeliveryLedger  # noqa: E402

# Create Flask app
app = Flask(
    __name__,
    template_folder='frontend/pages',
    static_folder='frontend',
    static_url_path=''
)
CORS(app)

# ==================== Rate Limiting & CSRF Middleware ====================
import time  # noqa: E402
from functools import wraps  # noqa: E402

auth_rates = {}


def rate_limit(max_requests=5, window=60):
    """Simple in-memory rate limiter for auth endpoints"""
    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            ip = request.remote_addr
            now = time.time()
            if ip not in auth_rates:
                auth_rates[ip] = []

            # Clean up old requests
            auth_rates[ip] = [req_time for req_time in auth_rates[ip] if now - req_time < window]

            if len(auth_rates[ip]) >= max_requests:
                return jsonify({'error': 'Rate limit exceeded. Try again later.'}), 429

            auth_rates[ip].append(now)
            return f(*args, **kwargs)
        return wrapped
    return decorator


@app.before_request
def csrf_protect():
    """Simple CSRF protection verifying standard JSON structure or origin"""
    if request.method == "POST":
        # Check standard headers for JSON API to prevent basic CSRF
        if request.content_type != 'application/json':
            return jsonify({'error': 'Unsupported Media Type, expected application/json'}), 415


# Application state
@dataclass
class AppState:
    """Global application state"""
    user: Optional[TelegramUser] = None
    is_scanning: bool = False
    is_sending: bool = False
    groups: List[Group] = field(default_factory=list)
    inactive_groups: List[Group] = field(default_factory=list)
    active_groups: List[Group] = field(default_factory=list)
    threshold_datetime: Optional[datetime] = None
    logs: List[Dict[str, Any]] = field(default_factory=list)
    last_scan_time: Optional[datetime] = None
    _is_dirty: bool = False

    def mark_dirty(self):
        self._is_dirty = True

    def add_log(self, message: str, level: str = "info"):
        """Add a log entry"""
        entry = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'level': level,
            'message': message
        }
        self.logs.append(entry)
        # Keep only last 1000 logs
        if len(self.logs) > 1000:
            self.logs = self.logs[-1000:]
        logger.log(getattr(logging, level.upper()), message)

    def get_statistics(self) -> Dict[str, Any]:
        """Get dashboard statistics with dynamic active/inactive computation"""
        # Compute active/inactive dynamically from groups data
        active_count = 0
        inactive_count = 0

        if self.groups:
            if self.active_groups or self.inactive_groups:
                # Use explicitly filtered results if available
                active_count = len(self.active_groups)
                inactive_count = len(self.inactive_groups)
            else:
                # Auto-compute using a default 30-day threshold
                from datetime import timedelta
                now = datetime.now(timezone.utc)
                default_threshold = now - timedelta(days=30)

                for g in self.groups:
                    if g.last_message_time:
                        msg_time = g.last_message_time
                        if msg_time.tzinfo is None:
                            msg_time = msg_time.replace(tzinfo=timezone.utc)
                        if msg_time >= default_threshold:
                            active_count += 1
                        else:
                            inactive_count += 1
                    else:
                        inactive_count += 1  # No message time = inactive

        return {
            'total_groups': len(self.groups),
            'active_groups': active_count,
            'inactive_groups': inactive_count,
            'is_authenticated': client_manager.is_authenticated,
            'user': {
                'id': self.user.id if self.user else None,
                'name': self.user.display_name if self.user else None,
                'username': self.user.username if self.user else None
            } if self.user else None,
            'last_scan': self.last_scan_time.isoformat() if self.last_scan_time else None,
            'threshold': self.threshold_datetime.isoformat() if self.threshold_datetime else None,
            'is_scanning': self.is_scanning,
            'is_sending': self.is_sending
        }


import threading  # noqa: E402

# Global state
app_state = AppState()
app_state_lock = threading.Lock()

# Inactivity filter instance
inactivity_filter: Optional[InactivityFilter] = None


# ==================== Load Persisted State ====================

def _load_persisted_state():
    """Load groups and app state from disk on startup"""
    try:
        # Load groups
        groups_data = persistence.load_groups()
        if groups_data:
            app_state.groups = [Group.from_dict(g) for g in groups_data]
            logger.info(f"Restored {len(app_state.groups)} groups from disk")

        # Load app metadata
        state_data = persistence.load_app_state()
        if state_data:
            if state_data.get('last_scan_time'):
                app_state.last_scan_time = datetime.fromisoformat(state_data['last_scan_time'])
            if state_data.get('threshold_datetime'):
                app_state.threshold_datetime = datetime.fromisoformat(state_data['threshold_datetime'])

        # Ensure sending flag is reset on startup
        app_state.is_sending = False
        app_state.is_scanning = False

    except Exception as e:
        logger.error(f"Failed to load persisted state: {e}")


_load_persisted_state()


# ==================== Initialize Ad Delivery System ====================

content_manager = ContentManager(config.content_dir)
delivery_engine = DeliveryEngine(
    max_retries=config.delivery_max_retries,
    inter_send_delay=config.delivery_inter_delay,
)
telegram_adapter = TelegramAdapter(client_manager)
delivery_engine.register_adapter(telegram_adapter)
delivery_ledger = DeliveryLedger(config.delivery_ledger_path)
ad_scheduler = AdScheduler(
    content_manager=content_manager,
    delivery_engine=delivery_engine,
    ledger=delivery_ledger,
    schedule_hour=config.schedule_hour,
    schedule_minute=config.schedule_minute,
    timezone_str=config.schedule_timezone,
)
ad_scheduler.set_log_callback(lambda msg: app_state.add_log(msg))

# Global event loop for background tasks and Telegram client
_global_loop = asyncio.new_event_loop()


async def automation_worker():
    """Background task to process automation rules periodically"""
    while True:
        try:
            await asyncio.sleep(60)  # Check every minute

            if not client_manager.is_authenticated:
                continue
            with app_state_lock:
                # Handle periodic save if dirty
                if getattr(app_state, '_is_dirty', False):
                    try:
                        persistence.save_groups([g.to_dict() for g in app_state.groups])
                        app_state._is_dirty = False
                        logger.debug("Saved groups to disk (live scan update)")
                    except Exception as e:
                        logger.error(f"Failed to auto-save groups: {e}")

                if app_state.is_scanning or app_state.is_sending or sender.is_running:
                    continue
                current_groups = list(app_state.groups)

            active_rules = [r for r in rules_engine.get_rules() if r.is_active]
            if not active_rules or not current_groups:
                continue

            from datetime import timedelta
            now = datetime.now(timezone.utc)

            for rule in active_rules:
                with app_state_lock:
                    if sender.is_running or app_state.is_sending:
                        break

                if rule.period_unit == 'Minutes':
                    delta = timedelta(minutes=rule.period_value)
                elif rule.period_unit == 'Hours':
                    delta = timedelta(hours=rule.period_value)
                else:
                    delta = timedelta(days=rule.period_value)

                threshold_time = now - delta

                groups_to_send = []
                for g in current_groups:
                    if g.last_message_time:
                        try:
                            msg_time = g.last_message_time
                            if msg_time.tzinfo is None:
                                msg_time = msg_time.replace(tzinfo=timezone.utc)
                            if msg_time < threshold_time:
                                groups_to_send.append(g)
                        except Exception:
                            groups_to_send.append(g)
                    else:
                        groups_to_send.append(g)

                if groups_to_send:
                    config_obj = AutomationConfig(
                        message_template=rule.message,
                        delay_min=10,
                        delay_max=30,
                        max_messages=1000,
                        dry_run=False
                    )

                    with app_state_lock:
                        app_state.is_sending = True
                    app_state.add_log(f"Auto-rule triggered: {len(groups_to_send)} groups detected")
                    try:
                        results = await sender.send_messages(
                            groups_to_send,
                            config_obj,
                            log_callback=lambda msg: app_state.add_log(msg)
                        )

                        successful_ids = {r.group_id for r in results if r.status == SendStatus.SENT}
                        if successful_ids:
                            now = datetime.now(timezone.utc)
                            with app_state_lock:
                                for g in app_state.groups:
                                    if g.id in successful_ids:
                                        g.last_message_time = now
                                groups_snapshot = [g.to_dict() for g in app_state.groups]
                            persistence.save_groups(groups_snapshot)

                    except Exception as e:
                        app_state.add_log(f"Auto-rule error: {e}", "error")
                    finally:
                        with app_state_lock:
                            app_state.is_sending = False

                    # Stop after executing one rule to avoid flooding
                    # Next minute it can evaluate the remaining/others if necessary
                    break

        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Automation worker error: {e}")


def _start_background_loop(loop):
    asyncio.set_event_loop(loop)
    loop.create_task(automation_worker())
    loop.run_forever()


_loop_thread = threading.Thread(target=_start_background_loop, args=(_global_loop,), daemon=True)
_loop_thread.start()


def run_async(coro):
    """Run async coroutine in sync context safely"""
    future = asyncio.run_coroutine_threadsafe(coro, _global_loop)
    return future.result()


# ==================== Live Scanner Event Handler ====================
async def live_scan_handler(event):
    """Event handler for new messages to update group last_message_time"""
    if not client_manager.is_authenticated or not event.chat_id:
        return

    chat_id = event.chat_id
    # Ensure ID matches our internal format (Telethon sometimes prefixes group IDs with -100)

    with app_state_lock:
        if not app_state.groups:
            return

        # Try finding the exact ID or the normalized ID
        base_id1 = chat_id
        base_id2 = chat_id
        if str(chat_id).startswith('-100'):
            base_id2 = int(str(chat_id)[4:])
        elif chat_id < 0:
            base_id2 = -chat_id

        found = False
        for g in app_state.groups:
            # Match directly or by base ID
            id_match = (g.id == chat_id
                        or str(g.id).replace('-100', '') == str(base_id1).replace('-100', '')
                        or g.id == base_id2)
            if id_match:
                g.last_message_time = event.date
                found = True
                break

        if found:
            app_state.mark_dirty()


def register_live_scanner():
    """Register the live scanner event handler safely"""
    if client_manager.client and client_manager.is_authenticated:
        try:
            # We intercept ONLY incoming messages
            client_manager.client.add_event_handler(live_scan_handler, events.NewMessage(incoming=True))
            logger.info("Live scanner registered successfully.")
        except Exception as e:
            logger.error(f"Failed to register live scanner: {e}")


# ==================== Routes ====================

@app.route('/')
def index():
    """Main dashboard page"""
    return render_template('index.html')


# ==================== Authentication API ====================

@app.route('/api/auth/status', methods=['GET'])
def auth_status():
    """Check authentication status"""
    return jsonify({
        'is_authenticated': client_manager.is_authenticated,
        'user': {
            'id': app_state.user.id if app_state.user else None,
            'name': app_state.user.display_name if app_state.user else None,
            'username': app_state.user.username if app_state.user else None
        } if app_state.user else None,
        'has_session': config.has_session
    })


@app.route('/api/auth/login', methods=['POST'])
@rate_limit(max_requests=10, window=60)
def auth_login():
    """Login with session string"""
    data = request.get_json()
    session_string = data.get('session_string', '')

    if not session_string:
        return jsonify({'error': 'Session string required'}), 400

    app_state.add_log("Attempting to authenticate with session...")

    success = run_async(client_manager.start_with_session(session_string))

    if success:
        app_state.user = client_manager.user
        app_state.add_log(f"Authenticated as {app_state.user.display_name}")
        register_live_scanner()
        return jsonify({
            'success': True,
            'user': {
                'id': app_state.user.id,
                'name': app_state.user.display_name,
                'username': app_state.user.username
            }
        })

    app_state.add_log("Authentication failed", "error")
    return jsonify({'error': 'Authentication failed'}), 401


def save_credentials_to_env(api_id, api_hash, session_string):
    """Save credentials to .env file"""
    try:
        import dotenv
        env_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env')
        if not os.path.exists(env_file):
            env_file = '.env'

        dotenv.set_key(env_file, 'API_ID', str(api_id))
        dotenv.set_key(env_file, 'API_HASH', api_hash)
        if session_string:
            dotenv.set_key(env_file, 'SESSION_STRING', session_string)
            config.session_string = session_string
    except Exception as e:
        logger.error(f"Failed to save to .env: {e}")


@app.route('/api/auth/request-code', methods=['POST'])
@rate_limit(max_requests=5, window=60)
def auth_request_code():
    """Request SMS code for native phone login"""
    data = request.get_json()
    api_id = data.get('api_id')
    api_hash = data.get('api_hash')
    phone = data.get('phone')

    if not all([api_id, api_hash, phone]):
        return jsonify({'error': 'API ID, API Hash, and Phone are required'}), 400

    if not str(api_id).isdigit():
        return jsonify({'error': 'API ID must be numeric'}), 400

    config.api_id = str(api_id)
    config.api_hash = api_hash

    app_state.add_log(f"Requesting SMS code for {phone}...")

    try:
        phone_code_hash, code_type = run_async(client_manager.start_with_phone(phone))
        return jsonify({
            'success': True,
            'phone_code_hash': phone_code_hash,
            'code_type': code_type
        })
    except Exception as e:
        app_state.add_log(f"Failed to request code: {str(e)}", "error")
        return jsonify({'error': str(e)}), 400


@app.route('/api/auth/verify-code', methods=['POST'])
@rate_limit(max_requests=10, window=60)
def auth_verify_code():
    """Verify SMS code"""
    data = request.get_json()
    phone = data.get('phone')
    code = data.get('code')
    phone_code_hash = data.get('phone_code_hash')

    if not all([phone, code, phone_code_hash]):
        return jsonify({'error': 'Phone, code, and hash are required'}), 400

    app_state.add_log("Verifying SMS code...")

    from telethon.errors import SessionPasswordNeededError

    try:
        session_string = run_async(client_manager.verify_code(phone, code, phone_code_hash))
        if session_string:
            app_state.user = client_manager.user
            app_state.add_log(f"Authenticated as {app_state.user.display_name}")

            # Save to .env
            save_credentials_to_env(config.api_id, config.api_hash, session_string)
            register_live_scanner()

            return jsonify({
                'success': True,
                'user': {
                    'id': app_state.user.id,
                    'name': app_state.user.display_name,
                    'username': app_state.user.username
                },
                'session_string': session_string
            })
        return jsonify({'error': 'Invalid code'}), 400
    except SessionPasswordNeededError:
        app_state.add_log("2FA Password required", "info")
        return jsonify({
            'success': False,
            'password_required': True
        })
    except Exception as e:
        app_state.add_log(f"Verification failed: {str(e)}", "error")
        return jsonify({'error': str(e)}), 400


@app.route('/api/auth/verify-password', methods=['POST'])
@rate_limit(max_requests=10, window=60)
def auth_verify_password():
    """Verify 2FA password"""
    data = request.get_json()
    password = data.get('password')

    if not password:
        return jsonify({'error': 'Password is required'}), 400

    app_state.add_log("Verifying 2FA password...")

    try:
        session_string = run_async(client_manager.verify_password(password))
        if session_string:
            app_state.user = client_manager.user
            app_state.add_log(f"Authenticated as {app_state.user.display_name}")

            # Save to .env
            save_credentials_to_env(config.api_id, config.api_hash, session_string)

            return jsonify({
                'success': True,
                'user': {
                    'id': app_state.user.id,
                    'name': app_state.user.display_name,
                    'username': app_state.user.username
                },
                'session_string': session_string
            })
        return jsonify({'error': 'Verification failed'}), 400
    except Exception as e:
        app_state.add_log(f"Password verification failed: {str(e)}", "error")
        return jsonify({'error': str(e)}), 400


@app.route('/api/auth/logout', methods=['POST'])
def auth_logout():
    """Logout and disconnect"""
    run_async(client_manager.disconnect())
    app_state.user = None
    app_state.groups = []
    app_state.inactive_groups = []
    app_state.active_groups = []
    scanner.clear()
    app_state.add_log("Logged out successfully")

    return jsonify({'success': True})


# ==================== Group Scanner API ====================

@app.route('/api/groups/scan', methods=['POST'])
def scan_groups():
    """Scan all Telegram groups"""
    if not client_manager.is_authenticated:
        return jsonify({'error': 'Not authenticated'}), 401

    with app_state_lock:
        if app_state.is_scanning:
            return jsonify({'error': 'Scan already in progress'}), 400

        app_state.is_scanning = True
    app_state.add_log("Starting group scan...")

    def progress_callback(current: int, total: int, group_name: str):
        app_state.add_log(f"Scanning: {group_name} ({current}/{total})")

    async def _run_scan():
        try:
            groups = await scanner.scan_all_groups(progress_callback=progress_callback)

            with app_state_lock:
                app_state.groups = groups
                app_state.last_scan_time = datetime.now(timezone.utc)
                app_state.active_groups = []
                app_state.inactive_groups = []

            app_state.add_log(f"Scan complete. Found {len(groups)} groups")

            # Persist groups and state to disk
            persistence.save_groups([g.to_dict() for g in groups])
            persistence.save_app_state({
                'last_scan_time': app_state.last_scan_time.isoformat() if app_state.last_scan_time else None,
                'threshold_datetime': app_state.threshold_datetime.isoformat() if app_state.threshold_datetime else None
            })
        except Exception as e:
            app_state.add_log(f"Scan failed: {str(e)}", "error")
        finally:
            with app_state_lock:
                app_state.is_scanning = False

    # Start task in background loop
    asyncio.run_coroutine_threadsafe(_run_scan(), _global_loop)

    return jsonify({
        'success': True,
        'message': 'Scan started in background'
    })


@app.route('/api/groups', methods=['GET'])
def get_groups():
    """Get all scanned groups"""
    return jsonify({
        'groups': [g.to_dict() for g in app_state.groups],
        'count': len(app_state.groups)
    })


# ==================== Inactivity Filter API (Removed) ====================


# ==================== Message Automation API ====================

@app.route('/api/automation/send', methods=['POST'])
def send_messages():
    """Send messages (Broadcast)"""
    if not client_manager.is_authenticated:
        return jsonify({'error': 'Not authenticated'}), 401

    with app_state_lock:
        if app_state.is_sending:
            return jsonify({'error': 'Sending already in progress'}), 400
        app_state.is_sending = True

    data = request.get_json() or {}
    message_template = data.get('message', '')
    target = data.get('target', 'all')  # "all" or "inactive"

    if target == 'inactive':
        period_value = int(data.get('period_value', 30))
        period_unit = data.get('period_unit', 'Days')

        # Calculate threshold time
        from datetime import timedelta
        now = datetime.now(timezone.utc)
        if period_unit == 'Minutes':
            delta = timedelta(minutes=period_value)
        elif period_unit == 'Hours':
            delta = timedelta(hours=period_value)
        else:  # Days
            delta = timedelta(days=period_value)

        threshold_time = now - delta

        # Filter groups manually here
        groups_to_send = []
        for g in app_state.groups:
            if g.last_message_time:
                try:
                    # g.last_message_time is a datetime object from telethon (UTC)
                    msg_time = g.last_message_time
                    # Ensure both are aware or naive. Telethon dates are usually UTC aware.
                    # If msg_time is naive for some reason, make it aware.
                    if msg_time.tzinfo is None:
                        msg_time = msg_time.replace(tzinfo=timezone.utc)

                    if msg_time < threshold_time:
                        groups_to_send.append(g)
                except Exception as e:
                    logger.error(f"Error parsing date for {g.name}: {e}")
                    # If we can't parse, assume inactive and send
                    groups_to_send.append(g)
            else:
                # No message time = inactive
                groups_to_send.append(g)
    else:
        groups_to_send = app_state.groups

    if not groups_to_send:
        return jsonify({'error': 'No groups to send to (try scanning first or increasing filter period)'}), 400

    if not message_template.strip():
        return jsonify({'error': 'Message required'}), 400

    config_obj = AutomationConfig(
        message_template=message_template,
        delay_min=10,
        delay_max=30,
        max_messages=1000,
        dry_run=False
    )

    app_state.add_log(f"Starting broadcast to {target} groups...")

    def progress_callback(current: int, total: int, result):
        status = "sent" if result.status == SendStatus.SENT else "failed"
        app_state.add_log(
            f"Message {status} to {result.group_name} ({current}/{total})"
        )

    async def _run_send():
        try:
            results = await sender.send_messages(
                groups_to_send,
                config_obj,
                progress_callback=progress_callback
            )

            successful_ids = {r.group_id for r in results if r.status == SendStatus.SENT}
            if successful_ids:
                now = datetime.now(timezone.utc)
                with app_state_lock:
                    for g in app_state.groups:
                        if g.id in successful_ids:
                            g.last_message_time = now
                persistence.save_groups([g.to_dict() for g in app_state.groups])

            summary = sender.get_results_summary()
            app_state.add_log(
                f"Automation complete: {summary['sent']} sent, {summary['failed']} failed"
            )

        except Exception as e:
            app_state.add_log(f"Automation error: {str(e)}", "error")
        finally:
            with app_state_lock:
                app_state.is_sending = False

    # Run in background
    asyncio.run_coroutine_threadsafe(_run_send(), _global_loop)

    return jsonify({
        'success': True,
        'message': 'Broadcast started in background'
    })


@app.route('/api/automation/stop', methods=['POST'])
def stop_automation():
    """Stop ongoing automation"""
    sender.stop()
    app_state.add_log("Automation stop requested")
    return jsonify({'success': True})


@app.route('/api/automation/status', methods=['GET'])
def automation_status():
    """Get automation status"""
    return jsonify({
        'is_running': sender.is_running,
        'is_paused': sender.is_paused,
        'progress': sender.progress,
        'results': sender.get_results_summary()
    })


# ==================== Rules Engine API ====================

@app.route('/api/rules', methods=['GET'])
def get_rules():
    """Get all automation rules"""
    return jsonify({
        'rules': [r.to_dict() for r in rules_engine.get_rules()]
    })


@app.route('/api/rules', methods=['POST'])
def add_rule():
    """Add a new automation rule"""
    data = request.get_json()
    try:
        rule = AutomationRule.from_dict(data)
        rules_engine.add_rule(rule)
        app_state.add_log(f"Added new automation rule for {rule.period_value} {rule.period_unit}")
        return jsonify({'success': True, 'rule': rule.to_dict()})
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@app.route('/api/rules/<rule_id>', methods=['DELETE'])
def delete_rule(rule_id):
    """Delete an automation rule"""
    success = rules_engine.delete_rule(rule_id)
    if success:
        app_state.add_log(f"Deleted rule {rule_id}")
        return jsonify({'success': True})
    return jsonify({'error': 'Rule not found'}), 404


@app.route('/api/rules/<rule_id>/toggle', methods=['POST'])
def toggle_rule(rule_id):
    """Toggle a rule on or off"""
    data = request.get_json()
    is_active = data.get('is_active', True)
    rule = rules_engine.toggle_rule(rule_id, is_active)
    if rule:
        status = "enabled" if is_active else "disabled"
        app_state.add_log(f"Rule {rule_id} {status}")
        return jsonify({'success': True, 'rule': rule.to_dict()})
    return jsonify({'error': 'Rule not found'}), 404


# ==================== Ad Content API ====================

@app.route('/api/ads', methods=['GET'])
def get_ads():
    """Get all ad content"""
    return jsonify({
        'ads': [a.to_dict() for a in content_manager.get_all_ads()],
        'count': len(content_manager.get_all_ads())
    })


@app.route('/api/ads/today', methods=['GET'])
def get_todays_ad():
    """Get the ad selected for today"""
    from datetime import date as date_cls
    ad = content_manager.get_ad_for_date(date_cls.today())
    if ad:
        return jsonify({'ad': ad.to_dict()})
    return jsonify({'ad': None, 'message': 'No active ad for today'})


@app.route('/api/ads', methods=['POST'])
def add_ad():
    """Add a new ad to the content manager"""
    data = request.get_json()
    try:
        ad = AdContent.from_dict(data)
        if not ad.id:
            import uuid
            ad.id = str(uuid.uuid4())[:8]
        content_manager.add_ad(ad)
        app_state.add_log(f"Added ad: {ad.title} (id={ad.id})")
        return jsonify({'success': True, 'ad': ad.to_dict()})
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@app.route('/api/ads/<ad_id>', methods=['PUT'])
def update_ad(ad_id):
    """Update an existing ad"""
    data = request.get_json()
    ad = content_manager.update_ad(ad_id, data)
    if ad:
        app_state.add_log(f"Updated ad: {ad_id}")
        return jsonify({'success': True, 'ad': ad.to_dict()})
    return jsonify({'error': 'Ad not found'}), 404


@app.route('/api/ads/<ad_id>', methods=['DELETE'])
def delete_ad(ad_id):
    """Delete an ad"""
    if content_manager.delete_ad(ad_id):
        app_state.add_log(f"Deleted ad: {ad_id}")
        return jsonify({'success': True})
    return jsonify({'error': 'Ad not found'}), 404


# ==================== Ad Scheduler API ====================

@app.route('/api/ad-scheduler/status', methods=['GET'])
def ad_scheduler_status():
    """Get ad scheduler status"""
    return jsonify(ad_scheduler.get_status())


@app.route('/api/ad-scheduler/start', methods=['POST'])
def start_ad_scheduler():
    """Start the ad scheduler"""
    if not client_manager.is_authenticated:
        return jsonify({'error': 'Not authenticated'}), 401

    data = request.get_json() or {}

    # Update schedule if provided
    schedule_time = data.get('schedule_time', config.schedule_time)
    tz = data.get('timezone', config.schedule_timezone)
    try:
        hour, minute = int(schedule_time.split(':')[0]), int(schedule_time.split(':')[1])
    except (ValueError, IndexError):
        return jsonify({'error': 'Invalid schedule_time format. Use HH:MM'}), 400

    # Build destinations from current groups
    destinations = [
        Destination(id=str(g.id), name=g.name, type="telegram")
        for g in app_state.groups
    ]
    if not destinations:
        return jsonify({'error': 'No groups available. Scan groups first.'}), 400

    ad_scheduler.set_destinations(destinations)
    ad_scheduler.update_schedule(hour, minute, tz)
    ad_scheduler.start()

    app_state.add_log(f"Ad scheduler started: {hour:02d}:{minute:02d} ({tz})")
    return jsonify({'success': True, 'status': ad_scheduler.get_status()})


@app.route('/api/ad-scheduler/stop', methods=['POST'])
def stop_ad_scheduler():
    """Stop the ad scheduler"""
    ad_scheduler.stop()
    app_state.add_log("Ad scheduler stopped")
    return jsonify({'success': True})


@app.route('/api/ad-scheduler/trigger', methods=['POST'])
def trigger_ad_delivery():
    """Manually trigger ad delivery now (for testing)"""
    if not client_manager.is_authenticated:
        return jsonify({'error': 'Not authenticated'}), 401

    # Ensure destinations are set
    destinations = [
        Destination(id=str(g.id), name=g.name, type="telegram")
        for g in app_state.groups
    ]
    if not destinations:
        return jsonify({'error': 'No groups available'}), 400

    ad_scheduler.set_destinations(destinations)
    app_state.add_log("Manual ad delivery triggered")

    async def _run_delivery():
        try:
            results = await ad_scheduler.run_daily_delivery()
            success = sum(1 for r in results if r.status == DeliveryStatus.SUCCESS)
            failed = sum(1 for r in results if r.status == DeliveryStatus.FAILED)
            app_state.add_log(f"Manual delivery complete: {success} sent, {failed} failed")
        except Exception as e:
            app_state.add_log(f"Manual delivery error: {e}", "error")

    asyncio.run_coroutine_threadsafe(_run_delivery(), _global_loop)
    return jsonify({'success': True, 'message': 'Delivery triggered in background'})


@app.route('/api/ad-scheduler/ledger', methods=['GET'])
def get_delivery_ledger():
    """Get delivery ledger records"""
    from datetime import date as date_cls
    target = request.args.get('date', date_cls.today().isoformat())
    try:
        target_date = date_cls.fromisoformat(target)
    except ValueError:
        return jsonify({'error': 'Invalid date format. Use YYYY-MM-DD'}), 400

    records = delivery_ledger.get_records_for_date(target_date)
    return jsonify({
        'date': target,
        'records': [r.to_dict() for r in records],
        'count': len(records)
    })


# ==================== Dashboard API ====================

@app.route('/api/dashboard', methods=['GET'])
def dashboard():
    """Get dashboard data"""
    return jsonify(app_state.get_statistics())


# ==================== Logs API ====================

@app.route('/api/logs', methods=['GET'])
def get_logs():
    """Get application logs"""
    limit = request.args.get('limit', 100, type=int)
    return jsonify({
        'logs': app_state.logs[-limit:]
    })


@app.route('/api/logs/stream')
def stream_logs():
    """Stream logs as Server-Sent Events"""
    def generate():
        # Simple implementation - in production would use proper SSE
        yield f"data: {json.dumps({'logs': app_state.logs[-10:]})}\n\n"

    return Response(generate(), mimetype='text/event-stream')


# ==================== Export API ====================

@app.route('/api/export/groups', methods=['GET'])
def export_groups():
    """Export groups data"""
    format_type = request.args.get('format', 'json')

    if format_type == 'csv':
        # Generate CSV
        lines = ['ID,Name,Username,Last Message,Status']
        for g in app_state.groups:
            lines.append(
                f"{g.id},\"{g.name}\",{g.username or ''},"
                f"{g.last_message_time or ''},{('Active' if g.is_active else 'Inactive')}"
            )
        return Response('\n'.join(lines), mimetype='text/csv')

    return jsonify({
        'groups': [g.to_dict() for g in app_state.groups]
    })


# ==================== Error Handlers ====================

@app.errorhandler(404)
def not_found(e):
    return jsonify({'error': 'Not found'}), 404


@app.errorhandler(500)
def server_error(e):
    logger.error(f"Server error: {e}")
    return jsonify({'error': 'Internal server error'}), 500


# ==================== Main Entry Point ====================

if __name__ == '__main__':
    # Ensure directories exist
    os.makedirs('logs', exist_ok=True)
    os.makedirs('data', exist_ok=True)

    # Print startup info
    logger.info("=" * 50)
    logger.info("Telegram Group Messaging Automation")
    logger.info("=" * 50)
    logger.info(f"API Configured: {config.is_configured}")
    logger.info(f"Debug Mode: {config.debug}")
    logger.info(f"Host: {config.host}:{config.port}")

    # Run Flask app
    app.run(
        host=config.host,
        port=config.port,
        debug=config.debug
    )
