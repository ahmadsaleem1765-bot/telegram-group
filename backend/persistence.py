"""
Persistence Module

Simple JSON-based persistence for application state, groups, and rules.
Saves data to the 'data/' directory.
"""

import json
import os
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime

logger = logging.getLogger(__name__)

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data')

GROUPS_FILE = os.path.join(DATA_DIR, 'groups.json')
RULES_FILE = os.path.join(DATA_DIR, 'rules.json')
STATE_FILE = os.path.join(DATA_DIR, 'app_state.json')


def _ensure_data_dir():
    """Ensure the data directory exists"""
    os.makedirs(DATA_DIR, exist_ok=True)


def _safe_write_json(filepath: str, data: Any):
    """Safely write JSON data to a file (atomic write via temp file)"""
    _ensure_data_dir()
    temp_path = filepath + '.tmp'
    try:
        with open(temp_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, default=str)
        # Atomic rename (on Windows this may overwrite)
        if os.path.exists(filepath):
            os.remove(filepath)
        os.rename(temp_path, filepath)
    except Exception as e:
        logger.error(f"Failed to write {filepath}: {e}")
        if os.path.exists(temp_path):
            os.remove(temp_path)


def _safe_read_json(filepath: str) -> Optional[Any]:
    """Safely read JSON data from a file"""
    try:
        if os.path.exists(filepath):
            with open(filepath, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as e:
        logger.error(f"Failed to read {filepath}: {e}")
    return None


# ==================== Groups Persistence ====================

def save_groups(groups: List[Dict[str, Any]]):
    """Save groups list to disk"""
    _safe_write_json(GROUPS_FILE, groups)
    logger.info(f"Saved {len(groups)} groups to disk")


def load_groups() -> List[Dict[str, Any]]:
    """Load groups list from disk"""
    data = _safe_read_json(GROUPS_FILE)
    if data and isinstance(data, list):
        logger.info(f"Loaded {len(data)} groups from disk")
        return data
    return []


# ==================== Rules Persistence ====================

def save_rules(rules: List[Dict[str, Any]]):
    """Save automation rules to disk"""
    _safe_write_json(RULES_FILE, rules)
    logger.info(f"Saved {len(rules)} rules to disk")


def load_rules() -> List[Dict[str, Any]]:
    """Load automation rules from disk"""
    data = _safe_read_json(RULES_FILE)
    if data and isinstance(data, list):
        logger.info(f"Loaded {len(data)} rules from disk")
        return data
    return []


# ==================== App State Persistence ====================

def save_app_state(state: Dict[str, Any]):
    """Save app metadata (threshold, last scan time, etc.) to disk"""
    _safe_write_json(STATE_FILE, state)
    logger.info("Saved app state to disk")


def load_app_state() -> Dict[str, Any]:
    """Load app metadata from disk"""
    data = _safe_read_json(STATE_FILE)
    if data and isinstance(data, dict):
        logger.info("Loaded app state from disk")
        return data
    return {}
