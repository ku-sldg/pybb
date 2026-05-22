from __future__ import annotations

import logging
from typing import Optional

from pydantic import BaseModel, Field

from .blackboard import Blackboard
from .knowledge_source import KnowledgeSource

logger = logging.getLogger(__name__)


class BlackboardController(BaseModel):
    """
    Coordinates knowledge sources against the shared blackboard.

    Selection strategy: highest-priority eligible KS runs each cycle.
    Halts when no KS can contribute or max_cycles is reached.
    """

    blackboard: Blackboard = Field(default_factory=Blackboard)
    knowledge_sources: list[KnowledgeSource] = []
    max_cycles: int = 100
    cycle_count: int = 0

    model_config = {"arbitrary_types_allowed": True}

    def add_ks(self, ks: KnowledgeSource) -> None:
        self.knowledge_sources.append(ks)

    def run(self) -> Blackboard:
        for i in range(self.max_cycles):
            self.cycle_count = i + 1
            active = [
                ks for ks in self.knowledge_sources
                if ks.can_contribute(self.blackboard)
            ]
            if not active:
                logger.info("No active knowledge sources at cycle %d; halting.", self.cycle_count)
                break
            best = max(active, key=lambda ks: ks.priority)
            logger.info("Cycle %d: running '%s' (priority=%d)", self.cycle_count, best.name, best.priority)
            best.execute(self.blackboard)
        return self.blackboard

    def status(self) -> dict:
        return {
            "cycles_run": self.cycle_count,
            "blackboard_keys": self.blackboard.keys(),
            "hypothesis": self.blackboard.hypothesis,
            "history_length": len(self.blackboard.history),
        }
