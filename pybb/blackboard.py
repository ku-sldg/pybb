from pydantic import BaseModel
from typing import Any

class BlackboardEntry(BaseModel):
    predicate: str
    measurement: Any
    result: Any
    good_standing: bool = False
    ks_history: dict[str, int] = {} # str: name of KS, int: num of attempts

class Blackboard(BaseModel):
    entries: dict[str, BlackboardEntry] = {} # key: id of entry, value: entry itself
    history: list[tuple[str, BlackboardEntry]] = []
    escalate: dict[str, BlackboardEntry] = {} # escalate segment of blackboard
    
    def write_entry(self, key: str, predicate: str, measurement: Any, result: Any = None, partition: str = "certify") -> BlackboardEntry: # partition should be specified as "certify" or escalate
        existing = self.entries.get(key) if partition == "certify" else self.escalate.get(key)
        entry = BlackboardEntry(
            predicate=predicate,
            measurement=measurement,
            result=result,
            ks_history=existing.ks_history if existing else {})
        if partition == "certify":
            self.entries[key] = entry
        elif partition == "escalate":
            self.escalate[key] = entry
        self.history.append((key, entry))
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
            entry.ks_history[ks_name] = entry.ks_history.get(ks_name, 0) + 1 # initializes ks entry to 0 if doesn't exist, adds 1
        