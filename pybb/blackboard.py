from pydantic import BaseModel
from typing import Any

class BlackboardEntry(BaseModel):
    predicate: str
    measurement: Any
    result: Any
    good_standing: bool = False
    original_measurement: Any = None # initial measurement restored by controller on KS handoff
    ks_history: dict[str, int] = {} # str: name of KS, int: num of attempts

    model_config = {"frozen": True} # immutable entry. change to entry creates a new versioned entry

class Blackboard(BaseModel):
    entries: dict[str, BlackboardEntry] = {} # key: id of entry, value: entry itself
    history: list[tuple[str, BlackboardEntry]] = []
    escalate: dict[str, BlackboardEntry] = {} # escalate segment of blackboard
    
    def set_entry(self, key: str, entry: BlackboardEntry) -> None:
        """reassign the certify slot and add snapshot to history. skip pre eval (result=None) intermediate states"""
        self.entries[key] = entry
        if entry.result is not None:
            self.history.append((key, entry.model_copy(deep=True)))

    def write_entry(self, key: str, predicate: str, measurement: Any, result: Any = None, partition: str = "certify") -> BlackboardEntry: # partition should be specified as "certify" or escalate
        existing = self.entries.get(key) if partition == "certify" else self.escalate.get(key)
        entry = BlackboardEntry(
            predicate=predicate,
            measurement=measurement,
            result=result,
            original_measurement=existing.original_measurement if existing else measurement,
            ks_history=dict(existing.ks_history) if existing else {}) # copy so versions don't share the dict
        if partition == "certify":
            self.set_entry(key, entry)
        elif partition == "escalate":
            self.escalate[key] = entry
        return entry

    def get_entry(self, key: str) -> BlackboardEntry:
        entry = self.entries.get(key)
        return entry if entry else None

    def get_all_entries(self) -> dict:
        return self.entries
    
    def get_history(self) -> list:
        return self.history
    
    def get_escalate(self) -> dict:
        return self.escalate

    def add_ks_history(self, key: str, ks_name: str ) -> None:
        entry = self.entries.get(key)
        if entry is not None:
            new_hist = dict(entry.ks_history)
            new_hist[ks_name] = new_hist.get(ks_name, 0) + 1 # initializes ks entry to 0 if doesn't exist, adds 1
            self.set_entry(key, entry.model_copy(update={"ks_history": new_hist}))

    def restore_original(self, key: str) -> None:
        entry = self.entries.get(key)
        if entry is not None:
            self.set_entry(key, entry.model_copy(update={"measurement": entry.original_measurement}))
        