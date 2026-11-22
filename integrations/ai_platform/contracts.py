"""Versioned, side-effect-free contracts for the future AI Core bridge.

This module deliberately performs no network calls and is not imported by the
existing Streamlit app or scanner worker. It establishes a stable boundary
before any service-to-service integration is enabled.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping
from uuid import uuid4


TASK_SCHEMA_VERSION = "1.0"
RESULT_SCHEMA_VERSION = "1.0"
TASK_PRIORITIES = frozenset({"low", "normal", "high", "urgent"})
TASK_STATUSES = frozenset({"pending", "running", "completed", "failed", "rejected"})


def _required_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string.")
    return value.strip()


def _mapping(value: Any, field_name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field_name} must be an object.")
    return dict(value)


@dataclass(frozen=True)
class TaskEnvelope:
    """Portable task request exchanged between the AI Core and project agents."""

    task_id: str
    project: str
    agent: str
    action: str
    priority: str = "normal"
    input: dict[str, Any] = field(default_factory=dict)
    constraints: dict[str, Any] = field(default_factory=dict)
    approval_required: bool = False
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    schema_version: str = TASK_SCHEMA_VERSION

    @classmethod
    def create(
        cls,
        *,
        project: str,
        agent: str,
        action: str,
        input: Mapping[str, Any] | None = None,
        constraints: Mapping[str, Any] | None = None,
        priority: str = "normal",
        approval_required: bool = False,
    ) -> "TaskEnvelope":
        task = cls(
            task_id=str(uuid4()),
            project=project,
            agent=agent,
            action=action,
            priority=priority,
            input=dict(input or {}),
            constraints=dict(constraints or {}),
            approval_required=approval_required,
        )
        task.validate()
        return task

    def validate(self) -> None:
        if self.schema_version != TASK_SCHEMA_VERSION:
            raise ValueError(f"Unsupported task schema version: {self.schema_version}.")
        for name in ("task_id", "project", "agent", "action", "created_at"):
            _required_text(getattr(self, name), name)
        if self.priority not in TASK_PRIORITIES:
            raise ValueError(f"priority must be one of {sorted(TASK_PRIORITIES)}.")
        _mapping(self.input, "input")
        _mapping(self.constraints, "constraints")
        if not isinstance(self.approval_required, bool):
            raise ValueError("approval_required must be a boolean.")

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "TaskEnvelope":
        data = _mapping(payload, "task")
        task = cls(
            task_id=data.get("task_id"),
            project=data.get("project"),
            agent=data.get("agent"),
            action=data.get("action"),
            priority=data.get("priority", "normal"),
            input=data.get("input", {}),
            constraints=data.get("constraints", {}),
            approval_required=data.get("approval_required", False),
            created_at=data.get("created_at"),
            schema_version=data.get("schema_version", TASK_SCHEMA_VERSION),
        )
        task.validate()
        return task


@dataclass(frozen=True)
class TaskResult:
    """Auditable result returned by a project agent."""

    task_id: str
    status: str
    result: dict[str, Any] = field(default_factory=dict)
    evidence: list[dict[str, Any]] = field(default_factory=list)
    confidence: float | None = None
    metrics: dict[str, Any] = field(default_factory=dict)
    errors: list[dict[str, Any]] = field(default_factory=list)
    completed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    schema_version: str = RESULT_SCHEMA_VERSION

    def validate(self) -> None:
        _required_text(self.task_id, "task_id")
        _required_text(self.completed_at, "completed_at")
        if self.schema_version != RESULT_SCHEMA_VERSION:
            raise ValueError(f"Unsupported result schema version: {self.schema_version}.")
        if self.status not in TASK_STATUSES:
            raise ValueError(f"status must be one of {sorted(TASK_STATUSES)}.")
        _mapping(self.result, "result")
        _mapping(self.metrics, "metrics")
        if not isinstance(self.evidence, list) or not all(isinstance(x, Mapping) for x in self.evidence):
            raise ValueError("evidence must be a list of objects.")
        if not isinstance(self.errors, list) or not all(isinstance(x, Mapping) for x in self.errors):
            raise ValueError("errors must be a list of objects.")
        if self.confidence is not None:
            if isinstance(self.confidence, bool) or not isinstance(self.confidence, (int, float)):
                raise ValueError("confidence must be a number between 0 and 1.")
            if not 0 <= float(self.confidence) <= 1:
                raise ValueError("confidence must be a number between 0 and 1.")

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "TaskResult":
        data = _mapping(payload, "task result")
        item = cls(
            task_id=data.get("task_id"),
            status=data.get("status"),
            result=data.get("result", {}),
            evidence=data.get("evidence", []),
            confidence=data.get("confidence"),
            metrics=data.get("metrics", {}),
            errors=data.get("errors", []),
            completed_at=data.get("completed_at"),
            schema_version=data.get("schema_version", RESULT_SCHEMA_VERSION),
        )
        item.validate()
        return item
