"""
Rules Engine Module

Manages multiple automation rules for inactive groups.
"""

import json
import logging
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field
import uuid
from datetime import datetime

logger = logging.getLogger(__name__)

@dataclass
class AutomationRule:
    """Defines a rule for automation"""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    period_value: int = 30
    period_unit: str = "Days"  # "Minutes", "Hours", "Days"
    message: str = ""
    is_active: bool = True
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'period_value': self.period_value,
            'period_unit': self.period_unit,
            'message': self.message,
            'is_active': self.is_active,
            'created_at': self.created_at
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'AutomationRule':
        return cls(
            id=data.get('id', str(uuid.uuid4())),
            period_value=data.get('period_value', 30),
            period_unit=data.get('period_unit', 'Days'),
            message=data.get('message', ''),
            is_active=data.get('is_active', True),
            created_at=data.get('created_at', datetime.now().isoformat())
        )

class RulesEngine:
    """Manages automation rules"""
    def __init__(self):
        self.rules: List[AutomationRule] = []

    def get_rules(self) -> List[AutomationRule]:
        return self.rules

    def add_rule(self, rule: AutomationRule) -> AutomationRule:
        self.rules.append(rule)
        return rule

    def delete_rule(self, rule_id: str) -> bool:
        initial_len = len(self.rules)
        self.rules = [r for r in self.rules if r.id != rule_id]
        return len(self.rules) < initial_len
    
    def toggle_rule(self, rule_id: str, is_active: bool) -> Optional[AutomationRule]:
        for rule in self.rules:
            if rule.id == rule_id:
                rule.is_active = is_active
                return rule
        return None

# Global rules engine instance
rules_engine = RulesEngine()
