"""
Telegram Group Messaging Automation - Main Application

A Flask-based web application for managing Telegram group automation.
"""

import os
import json
import asyncio
import logging
from datetime import datetime
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field, asdict

from flask import Flask, render_template, request, jsonify, Response
from flask_cors import CORS

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/app.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Import configuration
from config import config

# Import backend modules
from backend.telegram_client import client_manager, TelegramUser
from backend.group_scanner import scanner, Group
from backend.inactivity_filter import create_inactivity_filter, InactivityFilter
from backend.message_sender import sender, AutomationConfig, SendStatus
from backend.scheduler import scheduler, Schedule, ScheduleType

# Create Flask app
app = Flask(__name__, 
    template_folder='frontend/pages',
    static_folder='frontend',
    static_url_path=''
)
CORS(app)

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
    
    def add_log(self, message: str, level: str = "info"):
        """Add a log entry"""
        entry = {
            'timestamp': datetime.now().isoformat(),
            'level': level,
            'message': message
        }
        self.logs.append(entry)
        # Keep only last 1000 logs
        if len(self.logs) > 1000:
            self.logs = self.logs[-1000:]
        logger.log(getattr(logging, level.upper()), message)
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get dashboard statistics"""
        return {
            'total_groups': len(self.groups),
            'active_groups': len(self.active_groups),
            'inactive_groups': len(self.inactive_groups),
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


# Global state
app_state = AppState()

# Inactivity filter instance
inactivity_filter: Optional[InactivityFilter] = None


def run_async(coro):
    """Run async coroutine in sync context"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


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
    
    if app_state.is_scanning:
        return jsonify({'error': 'Scan already in progress'}), 400
    
    app_state.is_scanning = True
    app_state.add_log("Starting group scan...")
    
    try:
        def progress_callback(current: int, total: int, group_name: str):
            app_state.add_log(f"Scanning: {group_name} ({current}/{total})")
        
        # Run async scan
        groups = run_async(scanner.scan_all_groups(progress_callback=progress_callback))
        
        app_state.groups = groups
        app_state.last_scan_time = datetime.now()
        app_state.add_log(f"Scan complete. Found {len(groups)} groups")
        
        return jsonify({
            'success': True,
            'groups': [g.to_dict() for g in groups],
            'count': len(groups)
        })
        
    except Exception as e:
        app_state.add_log(f"Scan failed: {str(e)}", "error")
        return jsonify({'error': str(e)}), 500
    finally:
        app_state.is_scanning = False


@app.route('/api/groups', methods=['GET'])
def get_groups():
    """Get all scanned groups"""
    return jsonify({
        'groups': [g.to_dict() for g in app_state.groups],
        'count': len(app_state.groups)
    })


# ==================== Inactivity Filter API ====================

@app.route('/api/filter/set-threshold', methods=['POST'])
def set_threshold():
    """Set inactivity threshold"""
    data = request.get_json()
    date_str = data.get('date')
    time_str = data.get('time', '00:00')
    
    if not date_str:
        return jsonify({'error': 'Date required'}), 400
    
    try:
        # Parse datetime
        threshold_dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
        
        # Create filter if not exists
        global inactivity_filter
        inactivity_filter = create_inactivity_filter(scanner)
        inactivity_filter.set_threshold(threshold_dt)
        
        app_state.threshold_datetime = threshold_dt
        app_state.add_log(f"Threshold set to: {threshold_dt}")
        
        return jsonify({
            'success': True,
            'threshold': threshold_dt.isoformat()
        })
        
    except ValueError as e:
        return jsonify({'error': f'Invalid date format: {e}'}), 400


@app.route('/api/filter/apply', methods=['POST'])
def apply_filter():
    """Apply inactivity filter"""
    global inactivity_filter
    
    if not app_state.groups:
        return jsonify({'error': 'No groups scanned'}), 400
    
    if inactivity_filter is None:
        return jsonify({'error': 'Threshold not set'}), 400
    
    try:
        active, inactive = inactivity_filter.filter_groups()
        
        app_state.active_groups = active
        app_state.inactive_groups = inactive
        
        app_state.add_log(
            f"Filter applied: {len(active)} active, {len(inactive)} inactive"
        )
        
        return jsonify({
            'success': True,
            'active_groups': [g.to_dict() for g in active],
            'inactive_groups': [g.to_dict() for g in inactive],
            'statistics': inactivity_filter.get_statistics()
        })
        
    except Exception as e:
        app_state.add_log(f"Filter error: {str(e)}", "error")
        return jsonify({'error': str(e)}), 500


@app.route('/api/filter/statistics', methods=['GET'])
def get_statistics():
    """Get filter statistics"""
    if inactivity_filter:
        return jsonify(inactivity_filter.get_statistics())
    
    return jsonify({
        'total_groups': len(app_state.groups),
        'active_groups': len(app_state.active_groups),
        'inactive_groups': len(app_state.inactive_groups),
        'threshold': app_state.threshold_datetime.isoformat() if app_state.threshold_datetime else None
    })


# ==================== Message Automation API ====================

@app.route('/api/automation/send', methods=['POST'])
def send_messages():
    """Send messages to inactive groups"""
    if not client_manager.is_authenticated:
        return jsonify({'error': 'Not authenticated'}), 401
    
    if app_state.is_sending:
        return jsonify({'error': 'Sending already in progress'}), 400
    
    if not app_state.inactive_groups:
        return jsonify({'error': 'No inactive groups to send to'}), 400
    
    data = request.get_json() or {}
    message_template = data.get('message', 'Hello! This group seems inactive. Just checking in!')
    delay_min = int(data.get('delay_min', 10))
    delay_max = int(data.get('delay_max', 30))
    max_messages = int(data.get('max_messages', 50))
    dry_run = data.get('dry_run', False)
    
    if not message_template.strip():
        return jsonify({'error': 'Message template required'}), 400
    
    config_obj = AutomationConfig(
        message_template=message_template,
        delay_min=delay_min,
        delay_max=delay_max,
        max_messages=max_messages,
        dry_run=dry_run
    )
    
    app_state.is_sending = True
    app_state.add_log(f"Starting message automation (dry_run={dry_run})...")
    
    if dry_run:
        app_state.add_log("DRY RUN MODE - No messages will be sent")
    
    try:
        def progress_callback(current: int, total: int, result):
            status = "sent" if result.status == SendStatus.SENT else "failed"
            app_state.add_log(
                f"Message {status} to {result.group_name} ({current}/{total})"
            )
        
        results = run_async(sender.send_messages(
            app_state.inactive_groups,
            config_obj,
            progress_callback=progress_callback
        ))
        
        summary = sender.get_results_summary()
        app_state.add_log(
            f"Automation complete: {summary['sent']} sent, {summary['failed']} failed"
        )
        
        return jsonify({
            'success': True,
            'results': [r.to_dict() for r in results],
            'summary': summary
        })
        
    except Exception as e:
        app_state.add_log(f"Automation error: {str(e)}", "error")
        return jsonify({'error': str(e)}), 500
    finally:
        app_state.is_sending = False


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
