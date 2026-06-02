"""
Minimal example: a two-KS system that detects an anomaly and proposes a hypothesis.
Reads and writes are gated by a Cedar policy.
"""

# Cedar integration notes
# -----------------------
# What changed on the `cedar` branch:
#   - pybb/policy.py: new `PolicyEngine` wrapping `cedarpy.is_authorized`,
#     plus `PolicyDenied` (subclass of `PermissionError`).
#   - pybb/blackboard.py: `Blackboard` now takes an optional `policy_engine`;
#     `write()` enforces, and `read(key, principal=...)` enforces and requires
#     a principal when an engine is set.
#   - pybb/__init__.py: exports `PolicyEngine`, `PolicyDenied`.
#   - pyproject.toml: adds `cedarpy>=4`.
#   - example.py (this file): defines a small policy set and wires it in.
#
# Cedar shape used:
#   - Principal: KnowledgeSource::"<name>"
#   - Action:    Action::"read" | Action::"write"
#   - Resource:  BlackboardKey::"<key>"
#
# No schema is supplied — Cedar runs in untyped mode. For stricter validation,
# pass a `schema=` to `PolicyEngine` (cedarpy accepts a dict or JSON string).
#
# Backward compatibility: when `policy_engine` is None, `Blackboard` behaves
# exactly as before — `read(key)` works without a principal.

import logging
logging.basicConfig(level=logging.INFO, format="%(message)s")

from pybb import Blackboard, BlackboardController, KnowledgeSource, PolicyEngine


POLICIES = """
permit (
    principal == KnowledgeSource::"SensorReader",
    action    == Action::"write",
    resource  == BlackboardKey::"sensor_data"
);

permit (
    principal == KnowledgeSource::"AnomalyDetector",
    action    == Action::"read",
    resource  == BlackboardKey::"sensor_data"
);

permit (
    principal == KnowledgeSource::"AnomalyDetector",
    action    == Action::"write",
    resource  == BlackboardKey::"anomaly"
);
"""


class SensorReader(KnowledgeSource):
    name: str = "SensorReader"
    priority: int = 10

    def can_contribute(self, bb: Blackboard) -> bool:
        return not bb.has("sensor_data")

    def execute(self, bb: Blackboard) -> None:
        bb.write("sensor_data", {"temp": 98.6, "pressure": 1.05}, source=self.name)


class AnomalyDetector(KnowledgeSource):
    name: str = "AnomalyDetector"
    priority: int = 5

    def can_contribute(self, bb: Blackboard) -> bool:
        return bb.has("sensor_data") and not bb.has("anomaly")

    def execute(self, bb: Blackboard) -> None:
        data = bb.read("sensor_data", principal=self.name)
        if data["pressure"] > 1.0:
            bb.write("anomaly", "high_pressure", source=self.name, confidence=0.9)
            bb.hypothesis = "Possible overpressure event"


if __name__ == "__main__":
    policy_engine = PolicyEngine(policies=POLICIES)
    controller = BlackboardController(blackboard=Blackboard(policy_engine=policy_engine))
    controller.add_ks(SensorReader())
    controller.add_ks(AnomalyDetector())
    controller.run()
    print("\nFinal status:", controller.status())
    print("Hypothesis:", controller.blackboard.hypothesis)
