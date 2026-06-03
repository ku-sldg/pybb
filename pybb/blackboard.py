from pydantic import BaseModel
from typing import Any

#TODO: partitioning of escalate

class BlackboardEntry(BaseModel):
    predicate: str
    measurement: Any
    result: Any
    good_standing: bool = False

class Blackboard(BaseModel):
    entries: dict[str, BlackboardEntry] = {} # key: id of entry, value: entry itself
    
    def write_entry(self, key: str, predicate: str, measurement: Any, result: Any = None) -> BlackboardEntry:
        entry = BlackboardEntry(
            predicate=predicate, 
            measurement=measurement, 
            result=result)
        self.entries[key] = entry
        return entry

    def get_entry(self, key: str) -> BlackboardEntry:
        entry = self.entries[key]
        return entry if entry else None

    def get_all_entries(self) -> dict:
        return self.entries