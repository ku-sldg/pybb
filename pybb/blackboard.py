from pydantic import BaseModel, model_validator
from typing import Any, Optional

class BlackboardEntry(BaseModel):
    predicate: Optional[str] = None # single-predicate entries
    conditions: Optional[dict[str, str]] = None # component-wise entries. component name -> predicate name
    measurement: Any = None
    result: Any = None
    good_standing: bool = False
    original_measurement: Any = None # initial measurement restored by controller on KS handoff
    ks_history: dict[str, int] = {} # str: name of KS, int: num of attempts

    model_config = {"frozen": True} # immutable entry. change to entry creates a new versioned entry

    @model_validator(mode="after")
    def _predicate_or_conditions(self):
        if self.predicate is None and self.conditions is None:
            raise ValueError("entry needs a predicate or conditions, otherwise it is never evaluated")
        return self

    def component_good(self, component: str) -> bool:
        """standing of a single component. falls back to overall standing for single-predicate entries"""
        if isinstance(self.result, dict):
            return bool(self.result.get(component))
        return self.good_standing

class Blackboard(BaseModel):
    entries: dict[str, BlackboardEntry] = {} # certify segment: trust questions under active judgment
    provision: dict[str, BlackboardEntry] = {} # provisioning requests, written by external events; evaluated before certify, no KS chains
    history: list[tuple[str, BlackboardEntry]] = []
    escalate: dict[str, BlackboardEntry] = {} # escalate segment of blackboard

    def _segment(self, partition: str) -> dict[str, BlackboardEntry]:
        segments = {"certify": self.entries, "provision": self.provision, "escalate": self.escalate}
        if partition not in segments:
            raise ValueError(f"unknown partition '{partition}'")
        return segments[partition]

    def set_entry(self, key: str, entry: BlackboardEntry, partition: str = "certify") -> None:
        """reassign the segment slot and add snapshot to history. skip pre eval (result=None) intermediate states"""
        self._segment(partition)[key] = entry
        if entry.result is not None:
            self.history.append((key, entry.model_copy(deep=True)))

    def write_entry(self, key: str, predicate: Optional[str] = None, measurement: Any = None, result: Any = None, partition: str = "certify", conditions: Optional[dict[str, str]] = None) -> BlackboardEntry: # partition: "certify", "provision", or "escalate"
        existing = self._segment(partition).get(key)
        entry = BlackboardEntry(
            predicate=predicate,
            conditions=conditions if conditions is not None else (existing.conditions if existing else None),
            measurement=measurement,
            result=result,
            original_measurement=existing.original_measurement if existing else (dict(measurement) if isinstance(measurement, dict) else measurement), # copy dicts so component writes never alias the original
            ks_history=dict(existing.ks_history) if existing else {}) # copy so versions don't share the dict
        if partition == "escalate":
            self.escalate[key] = entry
        else:
            self.set_entry(key, entry, partition=partition)
        return entry

    def write_component(self, key: str, component: str, value: Any) -> BlackboardEntry:
        """write a repair for a single component of a dict measurement, leaving other components untouched"""
        entry = self.entries.get(key)
        if entry is None or not isinstance(entry.measurement, dict):
            return entry
        new_measurement = dict(entry.measurement)
        new_measurement[component] = value
        updated = entry.model_copy(update={"measurement": new_measurement, "result": None, "good_standing": False}) # result=None: controller reeval in next cycle
        self.set_entry(key, updated)
        return updated

    def get_entry(self, key: str) -> BlackboardEntry:
        entry = self.entries.get(key)
        return entry if entry else None

    def get_all_entries(self) -> dict:
        return self.entries

    def get_provision(self) -> dict:
        return self.provision

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

    def restore_component(self, key: str, component: str) -> None:
        """restore a single component of a dict measurement from the original, preserving other components' fixes"""
        entry = self.entries.get(key)
        if entry is None or not isinstance(entry.measurement, dict) or not isinstance(entry.original_measurement, dict):
            return
        new_measurement = dict(entry.measurement)
        new_measurement[component] = entry.original_measurement.get(component)
        self.set_entry(key, entry.model_copy(update={"measurement": new_measurement}))
