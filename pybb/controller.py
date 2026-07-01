from typing import Callable

from pydantic import BaseModel, Field

from .blackboard import Blackboard
from .knowledge_source import KnowledgeSource

class BlackboardController(BaseModel):
    """
    NEEDS UPDATE
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
    routes: dict[str, list[KnowledgeSource]] = {} # entry key -> ordered eligible KS chain (controller-owned)
    max_cycles: int = 100
    cycle_count: int = 0

    model_config = {"arbitrary_types_allowed": True}

    def register_predicate(self, name: str, fn: Callable) -> None:
        self.predicate_registry[name] = fn

    def add_ks(self, ks: KnowledgeSource) -> None:
        self.knowledge_sources.append(ks)

    def route(self, key: str, ks_chain: list[KnowledgeSource]) -> None:
        """find KS eligible for key. place key in first eligible KS partition. controller assigned"""
        self.routes[key] = ks_chain
        for ks in ks_chain:
            if key in ks.partition:
                ks.partition.remove(key)
        if ks_chain:
            ks_chain[0].partition.append(key)

    def _advance(self, key: str, current: KnowledgeSource) -> None:
        """move key to next eligible KS after current KS reaches max attempts on key. restores original measurement or moves to escalate
        if no available KS remains"""
        if key in current.partition:
            current.partition.remove(key)
        chain = self.routes.get(key, [])
        names = [ks.name for ks in chain]
        idx = names.index(current.name) if current.name in names else -1
        nxt = chain[idx + 1] if 0 <= idx and idx + 1 < len(chain) else None
        if nxt is not None:
            self.blackboard.restore_original(key)
            nxt.partition.append(key)
            print(f"Cycle {self.cycle_count}: '{current.name}' exhausted on '{key}' - restoring original measurement, handing to '{nxt.name}'")
        else:
            self.blackboard.escalate[key] = self.blackboard.entries.pop(key)
            print(f"Cycle {self.cycle_count}: no eligible KS left for '{key}' - escalating with history")

    def _evaluate_entry(self, key: str) -> None:
        entry = self.blackboard.entries.get(key)
        if entry is None:
            return
        fn = self.predicate_registry.get(entry.predicate)
        if fn is None:
            return
        result = fn(entry.measurement)
        self.blackboard.set_entry(key, entry.model_copy(update={"result": result, "good_standing": bool(result)}))

    def _evaluate_all(self) -> None:
        for key in list(self.blackboard.entries):
            self._evaluate_entry(key)

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
                for key in list(ks.partition): # snapshot of partition. _advance changes partitions
                    entry = self.blackboard.entries.get(key)
                    if entry is None or entry.good_standing:
                        continue
                    if ks.max_attempts is not None and entry.ks_history.get(ks.name, 0) >= ks.max_attempts:
                        self._advance(key, ks)
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
    
