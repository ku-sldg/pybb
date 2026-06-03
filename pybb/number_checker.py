from .blackboard import Blackboard
from .knowledge_source import KnowledgeSource

# TODO: add another partition that is valid/no need repair
#TODO: add another knowledge source
#TODO: ask what knowledge source should pass to controller for reeval. KS should/shouldn't modify entry?

def less_than_3(num: int) -> bool:
    return num < 3


class NumberChecker(KnowledgeSource):
    name: str = "NumberChecker"
    partition: list[str] = ["less_than_3"]

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
