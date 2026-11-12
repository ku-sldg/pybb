import pytest
from pydantic import ValidationError

from pybb import (
    Entry,
    NumberAdder,
    NumberSubtractor,
    WorkflowSpec,
    is_positive,
    less_than_3,
)


def base_kwargs(**overrides):
    kwargs = dict(
        predicates={"less_than_3": less_than_3},
        entries={"lt3": Entry(predicate="less_than_3", measurement=5)},
        routes={"lt3": [NumberAdder()]},
    )
    kwargs.update(overrides)
    return kwargs


# well formed specs

def test_well_formed_default_spec():
    adder = NumberAdder()
    spec = WorkflowSpec(**base_kwargs(routes={"lt3": [adder]}))
    assert spec.max_cycles == 100
    assert spec.max_restarts_per_key == 10
    assert spec.entries["lt3"].partition == "certify"
    assert spec.routes["lt3"].on_fail[0] is adder


def test_bare_list_route_is_on_fail():
    adder = NumberAdder()
    spec = WorkflowSpec(**base_kwargs(routes={"lt3": [adder]}))
    assert spec.routes["lt3"].on_pass == []
    assert spec.routes["lt3"].on_fail[0] is adder


def test_same_ks_in_two_routes():
    sub = NumberSubtractor()
    spec = WorkflowSpec(**base_kwargs(
        predicates={"less_than_3": less_than_3, "is_positive": is_positive},
        entries={
            "lt3": Entry(predicate="less_than_3", measurement=5),
            "pos": Entry(predicate="is_positive", measurement=-1),
        },
        routes={"lt3": [sub], "pos": [sub]},
    ))
    assert spec.routes["lt3"].on_fail[0] is spec.routes["pos"].on_fail[0]


# entry errors

def test_entry_needs_predicate_or_conditions():
    with pytest.raises(ValidationError, match="needs a predicate or conditions"):
        Entry(measurement=5)

def test_entry_rejects_predicate_and_conditions():
    with pytest.raises(ValidationError, match="not both"):
        Entry(predicate="less_than_3",
              conditions={"x": "less_than_3"},
              measurement={"x": 5})


def test_typoed_field_fails():
    with pytest.raises(ValidationError, match="measurment"):
        Entry(predicate="less_than_3", measurment=5)


# workflow spec error validation

def test_unknown_predicate_name():
    with pytest.raises(ValidationError, match="not in predicates"):
        WorkflowSpec(**base_kwargs(
            entries={"lt3": Entry(predicate="nonexistent", measurement=5)}))


def test_unknown_predicate_name_in_conditions():
    with pytest.raises(ValidationError, match="not in predicates"):
        WorkflowSpec(**base_kwargs(
            entries={"lt3": Entry(conditions={"x": "nonexistent"},
                                  measurement={"x": 5})}))


def test_route_without_entry():
    with pytest.raises(ValidationError, match="no matching entry"):
        WorkflowSpec(**base_kwargs(routes={"ghost": [NumberAdder()]}))


def test_route_on_provision_entry():
    with pytest.raises(ValidationError, match="take no KS chains"):
        WorkflowSpec(**base_kwargs(
            entries={"lt3": Entry(predicate="less_than_3", measurement=5,
                                  partition="provision")}))


def test_same_ks_twice_in_one_chain_rejected():
    adder, sub = NumberAdder(), NumberSubtractor()
    with pytest.raises(ValidationError, match="appears twice in one chain"):
        WorkflowSpec(**base_kwargs(routes={"lt3": [adder, sub, adder]}))


def test_two_ks_same_name_rejected():
    with pytest.raises(ValidationError, match="share the name"):
        WorkflowSpec(**base_kwargs(
            predicates={"less_than_3": less_than_3, "is_positive": is_positive},
            entries={
                "lt3": Entry(predicate="less_than_3", measurement=5),
                "pos": Entry(predicate="is_positive", measurement=-1),
            },
            routes={"lt3": [NumberAdder()], "pos": [NumberAdder()]},
        ))
