from pathlib import Path

from pybb import BlackboardController
from pybb.dogtreat.iterative_verus_gen import (
    IterativeVerusGenKS,
    IterativeVerusResult,
    source_measurement,
)
import pybb.dogtreat.iterative_verus_gen as iterative_verus_gen


def _controller(target: Path, repair_fn):
    controller = BlackboardController()
    rung = IterativeVerusGenKS(repair_fn=repair_fn)

    def predicate(measurement):
        path = Path(measurement["file"])
        passed = path.read_text() == "repaired"
        return IterativeVerusResult(file=str(path), passed=passed)

    controller.register_predicate("verus", predicate)
    controller.add_ks(rung)
    controller.blackboard.write_entry(
        key="proof", predicate="verus", measurement=source_measurement(target))
    controller.route("proof", [rung])
    return controller


def test_iterative_generator_repair_rewrites_and_rechecks(tmp_path):
    target = tmp_path / "proof.rs"
    target.write_text("broken")
    controller = _controller(target, lambda path: "repaired")

    blackboard = controller.run()

    entry = blackboard.get_entry("proof")
    assert entry is not None and entry.good_standing
    assert target.read_text() == "repaired"
    assert entry.ks_history == {"repair:iterative-verus-gen": 1}
    assert entry.measurement["sha256"] == source_measurement(target)["sha256"]


def test_iterative_generator_failure_escalates(tmp_path):
    target = tmp_path / "proof.rs"
    target.write_text("broken")
    controller = _controller(target, lambda path: None)

    blackboard = controller.run()

    assert "proof" in blackboard.get_escalate()
    assert target.read_text() == "broken"


def test_predicate_rejects_nonzero_verus_without_parsed_errors(tmp_path,
                                                               monkeypatch):
    target = tmp_path / "proof.rs"
    target.write_text("source")

    class FailedVerus:
        errors = []
        returncode = 1

        def __init__(self, source):
            pass

        def run_verus(self):
            pass

    monkeypatch.setattr(iterative_verus_gen, "VerusHandler", FailedVerus)
    result = iterative_verus_gen.make_verus_predicate()(source_measurement(target))

    assert not result
    assert result.error == "verus exited with code 1"