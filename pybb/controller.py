from typing import Callable

from pydantic import BaseModel, Field

from .blackboard import Blackboard, BlackboardEntry
from .knowledge_source import KnowledgeSource

class BlackboardController(BaseModel):
    """
    for each cycle:
      1. eval all entries
        a. run predicate from registry
        b. set good_standing based on result
      2. ask each KS if can contribute
        a. iterates through all its keys to check if good_standing
      3. run all KS that can_contribute
         a. currently partitions are considered to be unique (two KS don't look at same key)
    stop when no KS can contribute or max_cycles is reached.
    """

    blackboard: Blackboard = Field(default_factory=Blackboard)
    knowledge_sources: list[KnowledgeSource] = []
    predicate_registry: dict[str, Callable] = {}
    max_cycles: int = 100 
    cycle_count: int = 0

    model_config = {"arbitrary_types_allowed": True}

    def register_predicate(self, name: str, fn: Callable) -> None:
        self.predicate_registry[name] = fn

    def add_ks(self, ks: KnowledgeSource) -> None:
        self.knowledge_sources.append(ks)

    def _evaluate_entry(self, entry: BlackboardEntry) -> None:
        fn = self.predicate_registry.get(entry.predicate)
        if fn is None:
            return
        result = fn(entry.measurement)
        entry.result = result
        entry.good_standing = bool(result)

    def _evaluate_all(self) -> None:
        for entry in self.blackboard.entries.values():
            self._evaluate_entry(entry)

    def run(self) -> Blackboard:
        for i in range(self.max_cycles):
            self.cycle_count = i + 1
            self._evaluate_all()
            active = [ks for ks in self.knowledge_sources if ks.can_contribute(self.blackboard)]
            if not active:
                print(f"Cycle {self.cycle_count}: all entries in good standing - halting")
                break
            for ks in active:
                bad_keys = []
                print(f"Cycle {self.cycle_count}: running '{ks.name}'")
                for key in ks.partition:
                    entry = self.blackboard.entries.get(key)
                    if entry is None or entry.good_standing:
                        continue
                    if ks.max_attempts is not None and entry.ks_history.get(ks.name, 0) >= ks.max_attempts:
                        print(f"Cycle {self.cycle_count}: '{ks.name}' exceeded max attempts on '{key}' - escalating")
                        self.blackboard.escalate[key] = self.blackboard.entries.pop(key)
                    else:
                        self.blackboard.add_ks_history(key, ks.name)
                        bad_keys.append(key)
                ks.execute(self.blackboard, bad_keys)
        return self.blackboard

    def status(self) -> dict:
        return {
            "cycles_run": self.cycle_count,
            "entries": self.blackboard.get_all_entries()
        }
    
