from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field

from .policy import PolicyEngine


class BlackboardEntry(BaseModel):
    """A single typed, timestamped entry on the blackboard."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    key: str
    value: Any
    source: str
    confidence: float = 1.0
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    tags: list[str] = []


class Blackboard(BaseModel):
    """The shared data structure read and written by all knowledge sources."""

    entries: dict[str, BlackboardEntry] = {}
    history: list[BlackboardEntry] = []
    hypothesis: Optional[str] = None
    policy_engine: Optional[PolicyEngine] = Field(default=None, exclude=True)

    model_config = {"arbitrary_types_allowed": True}

    def write(
        self,
        key: str,
        value: Any,
        source: str,
        confidence: float = 1.0,
        tags: list[str] | None = None,
    ) -> BlackboardEntry:
        if self.policy_engine is not None:
            self.policy_engine.enforce(source, "write", key)
        entry = BlackboardEntry(
            key=key,
            value=value,
            source=source,
            confidence=confidence,
            tags=tags or [],
        )
        self.entries[key] = entry
        self.history.append(entry)
        return entry

    def read(self, key: str, principal: str | None = None) -> Optional[Any]:
        if self.policy_engine is not None:
            if principal is None:
                raise PermissionError(
                    f"Blackboard has a policy_engine; read({key!r}) requires principal=..."
                )
            self.policy_engine.enforce(principal, "read", key)
        entry = self.entries.get(key)
        return entry.value if entry else None

    def has(self, key: str) -> bool:
        return key in self.entries

    def keys(self) -> list[str]:
        return list(self.entries.keys())

    def snapshot(self) -> dict:
        return self.model_dump()
