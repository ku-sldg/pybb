"""
Minimal example: a two-KS system that detects an anomaly and proposes a hypothesis.
"""
import logging
logging.basicConfig(level=logging.INFO, format="%(message)s")

from pybb import Blackboard, BlackboardController, KnowledgeSource


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
        data = bb.read("sensor_data")
        if data["pressure"] > 1.0:
            bb.write("anomaly", "high_pressure", source=self.name, confidence=0.9)
            bb.hypothesis = "Possible overpressure event"


if __name__ == "__main__":
    controller = BlackboardController()
    controller.add_ks(SensorReader())
    controller.add_ks(AnomalyDetector())
    controller.run()
    print("\nFinal status:", controller.status())
    print("Hypothesis:", controller.blackboard.hypothesis)
