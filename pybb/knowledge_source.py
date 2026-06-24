from abc import ABC, abstractmethod
from typing import Optional

from pydantic import BaseModel

from .blackboard import Blackboard


class KnowledgeSource(ABC, BaseModel):
    name: str
    partition: list[str]  # blackboard keys this KS is responsible for. assigned by controller route()
    max_attempts: Optional[int] = None

    def can_contribute(self, blackboard: Blackboard) -> bool:
        """return True if any entry in KS partition not in good standing."""
        for key in self.partition:
            entry = blackboard.get_entry(key)
            if entry is not None and not entry.good_standing:
                return True
        return False

    @abstractmethod
    def execute(self, blackboard: Blackboard, keys: list[str]) -> None:
        """write a repair suggestion to blackboard for entries not in good standing"""
        pass
