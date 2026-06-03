from pydantic import BaseModel
from typing import Any

class BlackboardEntry(BaseModel):
    key: str
    predicate: str # TODO: implement registry of predicate name mappings str and fn name
    measurement: Any
    result: Any

    
class Blackboard(BaseModel):
    entries: dict[str, BlackboardEntry] = {} # key: index of entry, value: entry itself
    
    def write_entry(self, key: str, predicate: str, measurement: Any, result: Any) -> BlackboardEntry:
        entry = BlackboardEntry(
            key=key, 
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