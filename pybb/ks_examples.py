from .blackboard import Blackboard
from .knowledge_source import KnowledgeSource

"""NUMBER CHECKER EXAMPLE"""

def less_than_3(num: int) -> bool:
    return num < 3

def is_positive(num: int) -> bool:
    return num > 0

def is_100(num: int) -> bool:
    return num == 100

class NumberSubtractor(KnowledgeSource):
    name: str = "NumberSubtractor"
    partition: list[str] = [] # controller assigns keys w/ route()
    max_attempts: int = 3

    def execute(self, blackboard: Blackboard, keys: list[str]) -> None:
        for key in keys:
            entry = blackboard.get_entry(key)
            if entry is None or entry.good_standing: # can remove this check later since only bad keys are in keys
                continue
            repaired = entry.measurement - 1
            blackboard.write_entry(
                key=key,
                predicate=entry.predicate,
                measurement=repaired,
                result=None  # controller reeval in next cycle
            )

class NumberAdder(KnowledgeSource):
    name: str = "NumberAdder"
    partition: list[str] = []
    max_attempts: int = 3

    def execute(self, blackboard: Blackboard, keys: list[str]) -> None:
        for key in keys:
            entry = blackboard.get_entry(key)
            if entry is None or entry.good_standing: # can remove this check later since only bad keys are in keys
                continue
            repaired = entry.measurement + 1
            blackboard.write_entry(
                key=key,
                predicate=entry.predicate,
                measurement=repaired,
                result=None  # controller reeval in next cycle
            )

class NumberNothinger(KnowledgeSource):
    name: str = "NumberNothinger"
    partition: list[str] = []
    max_attempts: int = 3

    def execute(self, blackboard: Blackboard, keys: list[str]) -> None:
        for key in keys:
            entry = blackboard.get_entry(key)
            if entry is None or entry.good_standing: # can remove this check later since only bad keys are in keys
                continue
            repaired = entry.measurement # does nothing
            blackboard.write_entry(
                key=key,
                predicate=entry.predicate,
                measurement=repaired,
                result=None  # controller reeval in next cycle
            )

"""COMPONENT (PAIR) EXAMPLE - each KS operates on one component of a dict measurement"""

class ComponentSubtractor(KnowledgeSource):
    partition: list[str] = [] # controller assigns keys w/ route()
    max_attempts: int = 3

    def execute(self, blackboard: Blackboard, keys: list[str]) -> None:
        for key in keys:
            entry = blackboard.get_entry(key)
            if entry is None or entry.component_good(self.component):
                continue
            repaired = entry.measurement[self.component] - 1
            blackboard.write_component(key, self.component, repaired) # only touches own component

class ComponentAdder(KnowledgeSource):
    partition: list[str] = []
    max_attempts: int = 3

    def execute(self, blackboard: Blackboard, keys: list[str]) -> None:
        for key in keys:
            entry = blackboard.get_entry(key)
            if entry is None or entry.component_good(self.component):
                continue
            repaired = entry.measurement[self.component] + 1
            blackboard.write_component(key, self.component, repaired) # only touches own component