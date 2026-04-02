"""
Persistence Module

Saves application state (groups, rules, delivery ledger, etc.) to PostgreSQL
when DATABASE_URL is set (e.g. Railway deployment).  Falls back to JSON files
in the 'data/' directory for local development.
"""

import json
import os
import logging
from typing import List, Dict, Any, Optional

from backend.db import db_set, db_get

logger = logging.getLogger(__name__)

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data')

GROUPS_FILE = os.path.join(DATA_DIR, 'groups.json')
RULES_FILE = os.path.join(DATA_DIR, 'rules.json')
STATE_FILE = os.path.join(DATA_DIR, 'app_state.json')
LEDGER_FILE = os.path.join(DATA_DIR, 'delivery_ledger.json')


def _ensure_data_dir():
    os.makedirs(DATA_DIR, exist_ok=True)


def _safe_write_json(filepath: str, data: Any):
    """Safely write JSON data to a file (atomic write via temp file)."""
    _ensure_data_dir()
    temp_path = filepath + '.tmp'
    try:
        with open(temp_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
        if os.path.exists(filepath):
            os.remove(filepath)
        os.rename(temp_path, filepath)
    except Exception as e:
        logger.error("Failed to write %s: %s", filepath, e)
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass


def _safe_read_json(filepath: str) -> Optional[Any]:
    """Safely read JSON data from a file."""
    _ensure_data_dir()
    try:
        if os.path.exists(filepath):
            with open(filepath, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as e:
        logger.error("Failed to read %s: %s", filepath, e)
    return None


# ==================== Groups Persistence ====================

def save_groups(groups: List[Dict[str, Any]]):
    """Save groups list."""
    if not db_set('groups', groups):
        _safe_write_json(GROUPS_FILE, groups)
    logger.info("Saved %d groups", len(groups))


def load_groups() -> List[Dict[str, Any]]:
    """Load groups list."""
    data = db_get('groups')
    if data is not None:
        return data if isinstance(data, list) else []
    data = _safe_read_json(GROUPS_FILE)
    if data and isinstance(data, list):
        logger.info("Loaded %d groups from file", len(data))
        return data
    return []


# ==================== Rules Persistence ====================

def save_rules(rules: List[Dict[str, Any]]):
    """Save automation rules."""
    if not db_set('rules', rules):
        _safe_write_json(RULES_FILE, rules)
    logger.info("Saved %d rules", len(rules))


def load_rules() -> List[Dict[str, Any]]:
    """Load automation rules."""
    data = db_get('rules')
    if data is not None:
        return data if isinstance(data, list) else []
    data = _safe_read_json(RULES_FILE)
    if data and isinstance(data, list):
        logger.info("Loaded %d rules from file", len(data))
        return data
    return []


# ==================== App State Persistence ====================

def save_app_state(state: Dict[str, Any]):
    """Save app metadata (threshold, last scan time, etc.)."""
    if not db_set('app_state', state):
        _safe_write_json(STATE_FILE, state)
    logger.info("Saved app state")


def load_app_state() -> Dict[str, Any]:
    """Load app metadata."""
    data = db_get('app_state')
    if data is not None:
        return data if isinstance(data, dict) else {}
    data = _safe_read_json(STATE_FILE)
    if data and isinstance(data, dict):
        logger.info("Loaded app state from file")
        return data
    return {}


# ==================== Delivery Ledger Persistence ====================

def save_delivery_ledger(records: List[Dict[str, Any]]):
    """Save delivery ledger records."""
    payload = {'records': records}
    if not db_set('delivery_ledger', payload):
        _safe_write_json(LEDGER_FILE, payload)
    logger.info("Saved %d delivery records", len(records))


def load_delivery_ledger() -> List[Dict[str, Any]]:
    """Load delivery ledger records."""
    data = db_get('delivery_ledger')
    if data is not None:
        return data.get('records', []) if isinstance(data, dict) else []
    data = _safe_read_json(LEDGER_FILE)
    if data and isinstance(data, dict):
        records = data.get('records', [])
        logger.info("Loaded %d delivery records from file", len(records))
        return records
    return []
