from pydantic import BaseModel
from typing import Any, Optional, Callable
from .knowledge_source import KnowledgeSource

class Entry(BaseModel):
    predicate: Optional[str] = None # single-predicate entries
    conditions: Optional[dict[str, str]] = None # component-wise entries
    measurement: Any = None
    partition: str = "certify"

    model_config = {"extra": "forbid"}

class RouteSpec(BaseModel):
    on_pass: Optional[list[KnowledgeSource]] = []
    on_fail: Optional[list[KnowledgeSource]] = []

    model_config = {"extra": "forbid"}

class WorkflowSpec(BaseModel):
    predicates: dict[str, Callable]
    entries: dict[str, Entry] = {}
    routes: dict[str, RouteSpec] = {}
    max_cycles: int = 100
    max_restarts_per_key: int = 10

    model_config = {"extra": "forbid"}