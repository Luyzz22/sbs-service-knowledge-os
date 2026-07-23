"""Configurable retention periods with timezone-safe expiry calculation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
import os
from typing import Mapping, Optional


class RecordClass(str, Enum):
    AI_INTERACTION = "ai_interaction"
    AUDIT_EVENT = "audit_event"
    CONTRACT_ACCEPTANCE = "contract_acceptance"
    DATA_SUBJECT_REQUEST = "data_subject_request"
    UPLOADED_CONTENT = "uploaded_content"


_ENV_KEYS = {
    RecordClass.AI_INTERACTION: "AI_INTERACTION_RETENTION_DAYS",
    RecordClass.AUDIT_EVENT: "AUDIT_EVENT_RETENTION_DAYS",
    RecordClass.CONTRACT_ACCEPTANCE: "CONTRACT_ACCEPTANCE_RETENTION_DAYS",
    RecordClass.DATA_SUBJECT_REQUEST: "DATA_SUBJECT_REQUEST_RETENTION_DAYS",
    RecordClass.UPLOADED_CONTENT: "UPLOADED_CONTENT_RETENTION_DAYS",
}

_OPERATIONAL_DEFAULTS = {
    RecordClass.AI_INTERACTION: 30,
    RecordClass.AUDIT_EVENT: 365,
    RecordClass.CONTRACT_ACCEPTANCE: 3650,
    RecordClass.DATA_SUBJECT_REQUEST: 1095,
    RecordClass.UPLOADED_CONTENT: 1,
}


@dataclass(frozen=True)
class RetentionPolicy:
    """Technical defaults that must be approved against the processing register."""

    days_by_class: Mapping[RecordClass, int]

    def __post_init__(self) -> None:
        missing = set(RecordClass) - set(self.days_by_class)
        if missing:
            names = ", ".join(sorted(item.value for item in missing))
            raise ValueError(f"Missing retention classes: {names}")
        for record_class, days in self.days_by_class.items():
            if not isinstance(days, int) or days <= 0:
                raise ValueError(f"Retention for {record_class.value} must be positive")

    @classmethod
    def from_environment(
        cls,
        environment: Optional[Mapping[str, str]] = None,
    ) -> "RetentionPolicy":
        values = environment if environment is not None else os.environ
        configured: dict[RecordClass, int] = {}
        for record_class, env_key in _ENV_KEYS.items():
            raw_value = values.get(env_key, str(_OPERATIONAL_DEFAULTS[record_class]))
            try:
                configured[record_class] = int(raw_value)
            except ValueError as error:
                raise ValueError(f"{env_key} must be an integer") from error
        return cls(configured)

    def expires_at(self, record_class: RecordClass, created_at: datetime) -> datetime:
        if created_at.tzinfo is None:
            raise ValueError("created_at must be timezone-aware")
        return created_at + timedelta(days=self.days_by_class[record_class])
