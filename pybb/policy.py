from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from cedarpy import Decision, is_authorized


class PolicyDenied(PermissionError):
    """Raised when a Cedar policy denies a blackboard action."""

    def __init__(
        self,
        principal: str,
        action: str,
        resource: str,
        errors: list[str] | None = None,
    ):
        self.principal = principal
        self.action = action
        self.resource = resource
        self.errors = errors or []
        msg = f"Cedar denied: {principal} -> {action} -> {resource}"
        if self.errors:
            msg += f" (engine errors: {self.errors})"
        super().__init__(msg)


@dataclass
class PolicyEngine:
    """Cedar-backed authorization for blackboard reads and writes.

    Requests are formed as:
        principal = KnowledgeSource::"<ks-name>"
        action    = Action::"read" | Action::"write"
        resource  = BlackboardKey::"<key>"
    """

    policies: str
    entities: list[dict[str, Any]] = field(default_factory=list)
    schema: dict | str | None = None
    principal_type: str = "KnowledgeSource"
    resource_type: str = "BlackboardKey"

    def _request(self, principal: str, action: str, resource: str, context: dict | None) -> dict:
        return {
            "principal": f'{self.principal_type}::"{principal}"',
            "action": f'Action::"{action}"',
            "resource": f'{self.resource_type}::"{resource}"',
            "context": context or {},
        }

    def check(
        self,
        principal: str,
        action: str,
        resource: str,
        context: dict | None = None,
    ) -> bool:
        req = self._request(principal, action, resource, context)
        result = is_authorized(req, self.policies, self.entities, self.schema)
        return result.decision == Decision.Allow

    def enforce(
        self,
        principal: str,
        action: str,
        resource: str,
        context: dict | None = None,
    ) -> None:
        req = self._request(principal, action, resource, context)
        result = is_authorized(req, self.policies, self.entities, self.schema)
        if result.decision != Decision.Allow:
            errors = [str(e) for e in (result.diagnostics.errors or [])]
            raise PolicyDenied(principal, action, resource, errors)
