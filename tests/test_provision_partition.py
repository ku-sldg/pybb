"""
Provision partition mechanics: requests evaluate before certify entries,
have no KS chains, escalate on first failure, and remain in the partition
as the provisioned record on success.
"""

from pybb import BlackboardController
from pybb.blackboard import Blackboard


def test_write_and_get_provision_partition():
    bb = Blackboard()
    bb.write_entry(key="provision:p1", predicate="prov",
                   measurement={"protocol": "p1"}, partition="provision")
    assert "provision:p1" in bb.get_provision()
    assert "provision:p1" not in bb.entries and "provision:p1" not in bb.escalate


def test_provision_evaluates_before_certify():
    order = []
    ctl = BlackboardController()
    ctl.register_predicate("prov", lambda m: order.append("provision") or True)
    ctl.register_predicate("cert", lambda m: order.append("certify") or True)
    # certify entry written FIRST; the provision partition must still win
    ctl.blackboard.write_entry(key="sys", predicate="cert", measurement=1)
    ctl.blackboard.write_entry(key="provision:p1", predicate="prov",
                               measurement={}, partition="provision")
    ctl.run()
    assert order[:2] == ["provision", "certify"]


def test_failed_provision_escalates_immediately():
    ctl = BlackboardController()
    ctl.register_predicate("prov", lambda m: False)
    ctl.blackboard.write_entry(key="provision:p1", predicate="prov",
                               measurement={}, partition="provision")
    bb = ctl.run()
    assert "provision:p1" not in bb.provision
    assert "provision:p1" in bb.escalate
    assert bb.escalate["provision:p1"].result is False


def test_successful_provision_stays_as_record():
    ctl = BlackboardController()
    ctl.register_predicate("prov", lambda m: {"ok": True})
    ctl.blackboard.write_entry(key="provision:p1", predicate="prov",
                               measurement={}, partition="provision")
    bb = ctl.run()
    entry = bb.provision["provision:p1"]
    assert entry.good_standing and entry.result == {"ok": True}
    # the provisioning act is on the audit trail
    assert any(k == "provision:p1" for k, e in bb.history)


def test_provision_partition_never_enters_ks_machinery():
    """KS partitions and dispatch stay certify-only."""
    from pybb.ks_examples import NumberAdder

    ctl = BlackboardController()
    ctl.register_predicate("prov", lambda m: False)
    ks = NumberAdder()
    ctl.add_ks(ks)
    ctl.blackboard.write_entry(key="provision:p1", predicate="prov",
                               measurement=0, partition="provision")
    ctl.run()
    assert ks.partition == []  # failure escalated without any dispatch
