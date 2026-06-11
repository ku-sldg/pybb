from .blackboard import Blackboard
from .knowledge_source import KnowledgeSource

"""NUMBER CHECKER EXAMPLE"""

def less_than_3(num: int) -> bool:
    return num < 3

def is_positive(num: int) -> bool:
    return num > 0


class NumberChecker(KnowledgeSource):
    name: str = "NumberChecker"
    partition: list[str] = ["less_than_3", "is_positive"]
    max_attempts: int = 3

    def execute(self, blackboard: Blackboard) -> None:
        for key in self.partition:
            entry = blackboard.get_entry(key)
            if entry is None or entry.good_standing:
                continue
            repaired = entry.measurement - 1
            blackboard.write_entry(
                key=key,
                predicate=entry.predicate,
                measurement=repaired,
                result=None  # controller reeval in next cycle
            )