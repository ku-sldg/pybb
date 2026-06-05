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
        entry = BlackboardEntry(
            predicate=predicate, 
            measurement=measurement, 
            result=result)
        if partition == "certify":
            self.entries[key] = entry
        elif partition == "escalate":
            self.escalate[key] = entry
        self.history.append((key, entry))
        return entry

    def get_entry(self, key: str) -> BlackboardEntry:
        entry = self.entries[key]
        return entry if entry else None

    def get_all_entries(self) -> dict:
        return self.entries
    
    def get_history(self) -> list:
        return self.history

    def add_ks_history(self, key, ks_name, ) -> dict:
        pass