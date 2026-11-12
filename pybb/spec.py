from pydantic import BaseModel, model_validator
from typing import Any, Optional, Callable, Literal
from .knowledge_source import KnowledgeSource

class Entry(BaseModel):
    predicate: Optional[str] = None # single-predicate entries
    conditions: Optional[dict[str, str]] = None # component-wise entries
    measurement: Any = None
    partition: Literal["certify", "provision"] = "certify"
    model_config = {"extra": "forbid"} # prevent pydantic from silently ignoring unknown fields

    @model_validator(mode="after")
    def _predicate_or_conditions(self):
        if self.predicate is None and self.conditions is None:
            raise ValueError("entry needs a predicate or conditions, otherwise it is never evaluated")
        if self.predicate is not None and self.conditions is not None:
            raise ValueError("give predicate or conditions, not both")
        return self

class RouteSpec(BaseModel):
    on_pass: list[KnowledgeSource] = []
    on_fail: list[KnowledgeSource] = []
    model_config = {"extra": "forbid"}

    @model_validator(mode="before")
    @classmethod
    def _bare_list_is_on_fail(cls, data): # RouteSpec validates anywhere where RouteSpec is expected. when user gives list form route, convert to on_fail structure
        if isinstance(data, list):
            return {"on_fail": data}
        return data

class WorkflowSpec(BaseModel):
    predicates: dict[str, Callable]
    entries: dict[str, Entry] = {}
    routes: dict[str, RouteSpec] = {}
    max_cycles: int = 100
    max_restarts_per_key: int = 10
    model_config = {"extra": "forbid"}

    @model_validator(mode="after")
    def _check_wiring(self):
        for key, entry in self.entries.items():
            names = list(entry.conditions.values()) if entry.conditions else [entry.predicate]
            for name in names:
                if name not in self.predicates:
                    raise ValueError(f"entry '{key}' references predicate '{name}', which is not in predicates")
        for key, route in self.routes.items():
            entry = self.entries.get(key)
            if entry is None:
                raise ValueError(f"route '{key}' has no matching entry")
            if entry.partition == "provision":
                raise ValueError(f"route '{key}': provision requests take no KS chains (failing request escalates directly)")
        seen: dict[str, int] = {}  # KS name -> id() of first instance seen with it
        for key, route in self.routes.items():
            for label, chain in (("on_pass", route.on_pass), ("on_fail", route.on_fail)):
                in_chain: set[str] = set()
                for ks in chain:
                    if ks.name in in_chain:
                        raise ValueError(f"route '{key}' {label}: KS name '{ks.name}' appears twice in one chain")
                    in_chain.add(ks.name)
                    if seen.setdefault(ks.name, id(ks)) != id(ks):
                        raise ValueError(f"two different KnowledgeSource instances share the name '{ks.name}'")
        return self