from .blackboard import Blackboard
from .knowledge_source import KnowledgeSource
from typing import List

class RestartEpisodeKS(KnowledgeSource):
    name: str = ""
    partition: List[str] = []
    max_attempts: int = 1
    budget: int = 1
    also: List[str] = []

    def model_post_init(self, __context) -> None:
        if not self.name:
            self.name = f"restart:budget{self.budget}"

    def execute(self, blackboard: Blackboard, keys: List[str]) -> None:
        for key in keys:
            if blackboard.restarts.get(key, 0) >= self.budget:
                continue
            blackboard.request_restart(key, "fresh episode after repair")
            for extra in self.also:
                if extra == key or blackboard.restarts.get(extra, 0) >= self.budget:
                    continue
                if extra in blackboard.escalate and extra not in blackboard.entries:
                    # revive: the sibling escalated on the pre-repair tree
                    blackboard.entries[extra] = blackboard.escalate.pop(extra)
                blackboard.request_restart(
                    extra, "sibling repair staled this verdict")