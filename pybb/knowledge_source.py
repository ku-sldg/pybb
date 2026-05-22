from __future__ import annotations

from abc import abstractmethod

from pydantic import BaseModel

from .blackboard import Blackboard


class KnowledgeSource(BaseModel):
    """
    Abstract base for all knowledge sources (experts/agents).

    Subclass this and implement `can_contribute` and `execute`.
    """

    name: str
    priority: int = 0

    model_config = {"arbitrary_types_allowed": True}

    @abstractmethod
    def can_contribute(self, blackboard: Blackboard) -> bool:
        """Return True if this KS has something to add given current blackboard state."""
        ...

    @abstractmethod
    def execute(self, blackboard: Blackboard) -> None:
        """Read from and write to the blackboard."""
        ...
