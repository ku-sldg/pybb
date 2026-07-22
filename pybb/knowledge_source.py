from abc import ABC, abstractmethod
from typing import Optional

from pydantic import BaseModel

from .blackboard import Blackboard, BlackboardEntry


class KnowledgeSource(ABC, BaseModel):
    name: str
    partition: list[str]  # blackboard keys this KS is responsible for. assigned by controller route()
    max_attempts: Optional[int] = None
    component: Optional[str] = None # scopes this KS to one component of a dict measurement

    def _needs_work(self, entry: BlackboardEntry) -> bool:
        """component-scoped KS only cares about its own component's standing"""
        if self.component is not None and entry.conditions is not None:
            return not entry.component_good(self.component)
        return not entry.good_standing

    def can_contribute(self, blackboard: Blackboard) -> bool:
        """return True if any entry in KS partition not in good standing."""
        for key in self.partition:
            entry = blackboard.get_entry(key)
            if entry is not None and self._needs_work(entry):
                return True
        return False

    @abstractmethod
    def execute(self, blackboard: Blackboard, keys: list[str]) -> None:
        """write a repair suggestion to blackboard for entries not in good standing.
        controller guarantees keys are existing entries that need work (_needs_work)"""
        pass
