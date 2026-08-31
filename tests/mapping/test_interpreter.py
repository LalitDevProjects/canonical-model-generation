"""Hermetic tests for mapping/interpreter.py::Plan - forward/reverse and
all four on_failure branches, in both directions."""

from __future__ import annotations

import pytest

from mapping.interpreter import Escalation, MappingRejected, Plan, Step, read_path, write_path
from mapping.parser import TransformCall
from mapping.transforms import TransformError

pytestmark = pytest.mark.unit


def _identity_step(*, canonical: str, region: str, on_failure: str = "escalate", weight: int = 3) -> Step:
    return Step(
        canonical_path=canonical,
        region_path=region,
        transform_chain=(TransformCall(name="identity", args={}),),
        disposition_status=None,
        on_failure=on_failure,  # type: ignore[arg-type]
        weight=weight,
        reversible=True,
        declared_loss_kind=None,
        note=None,
    )


def _failing_step(*, on_failure: str, weight: int = 5) -> Step:
    # valueMap raises TransformError whenever its input isn't a string,
    # regardless of direction - a reliable failure trigger in both
    # forward() (region.x is an int) and reverse() (canon.x is an int).
    return Step(
        canonical_path="canon.x",
        region_path="region.x",
        transform_chain=(TransformCall(name="valueMap", args={"map": "empty", "resolved_map": {}}),),
        disposition_status=None,
        on_failure=on_failure,  # type: ignore[arg-type]
        weight=weight,
        reversible=True,
        declared_loss_kind=None,
        note=None,
    )


class TestReadWritePath:
    def test_write_and_read_round_trip_nested_path(self) -> None:
        out: dict[str, object] = {}
        write_path(out, "a.b.c", 42)
        assert out == {"a": {"b": {"c": 42}}}
        assert read_path(out, "a.b.c") == 42

    def test_read_missing_path_returns_none(self) -> None:
        assert read_path({"a": {}}, "a.b.c") is None

    def test_write_none_path_is_a_noop(self) -> None:
        out: dict[str, object] = {}
        write_path(out, None, 42)
        assert out == {}

    def test_read_none_path_returns_none(self) -> None:
        assert read_path({"a": 1}, None) is None


class TestForward:
    def test_simple_mapping(self) -> None:
        plan = Plan(steps=(_identity_step(canonical="claimReference", region="ClaimNo"),))
        result = plan.forward({"ClaimNo": "CLM-1"})
        assert result == {"claimReference": "CLM-1"}

    def test_disposition_step_is_skipped(self) -> None:
        step = Step(
            canonical_path=None,
            region_path="LegacyBatchId",
            transform_chain=(),
            disposition_status="unmapped",
            on_failure="escalate",
            weight=1,
            reversible=False,
            declared_loss_kind=None,
            note=None,
        )
        plan = Plan(steps=(step,))
        result = plan.forward({"LegacyBatchId": "X"})
        assert result == {}


class TestOnFailureBranches:
    def test_reject_raises_mapping_rejected(self) -> None:
        plan = Plan(steps=(_failing_step(on_failure="reject"),))
        with pytest.raises(MappingRejected):
            plan.forward({"region": {"x": 10}})

    def test_escalate_records_escalation_and_continues(self) -> None:
        plan = Plan(steps=(_failing_step(on_failure="escalate"),))
        result = plan.forward({"region": {"x": 10}})
        assert result == {}
        assert len(plan.escalations) == 1
        assert isinstance(plan.escalations[0], Escalation)
        assert isinstance(plan.escalations[0].error, TransformError)

    def test_default_writes_none(self) -> None:
        plan = Plan(steps=(_failing_step(on_failure="default"),))
        result = plan.forward({"region": {"x": 10}})
        assert result == {"canon": {"x": None}}

    def test_skip_writes_nothing(self) -> None:
        plan = Plan(steps=(_failing_step(on_failure="skip"),))
        result = plan.forward({"region": {"x": 10}})
        assert result == {}


class TestReverse:
    def test_simple_reverse(self) -> None:
        plan = Plan(steps=(_identity_step(canonical="claimReference", region="ClaimNo"),))
        result = plan.reverse({"claimReference": "CLM-1"})
        assert result == {"ClaimNo": "CLM-1"}

    def test_step_mismarked_reversible_still_defends_against_undefined_reverse(self) -> None:
        # Steps are ordinarily only produced by mapping/compiler.py, which
        # keeps `reversible` consistent with the chain's own transforms.
        # A hand-built Step that violates that invariant (reversible=True
        # but the chain actually contains a no-reverse transform) must
        # still fail safely via TransformError -> escalate, not crash.
        step = Step(
            canonical_path="canon.x",
            region_path="region.x",
            transform_chain=(TransformCall(name="coalesce", args={}),),
            disposition_status=None,
            on_failure="escalate",
            weight=1,
            reversible=True,
            declared_loss_kind=None,
            note=None,
        )
        plan = Plan(steps=(step,))
        result = plan.reverse({"canon": {"x": ["a"]}})
        assert result == {}
        assert len(plan.escalations) == 1

    def test_non_reversible_step_is_skipped(self) -> None:
        step = Step(
            canonical_path="canon.x",
            region_path="region.x",
            transform_chain=(TransformCall(name="coalesce", args={}),),
            disposition_status=None,
            on_failure="escalate",
            weight=3,
            reversible=False,
            declared_loss_kind="undefined-reverse",
            note=None,
        )
        plan = Plan(steps=(step,))
        result = plan.reverse({"canon": {"x": "irrelevant"}})
        assert result == {}

    def test_reverse_reject_raises(self) -> None:
        plan = Plan(steps=(_failing_step(on_failure="reject"),))
        with pytest.raises(MappingRejected):
            plan.reverse({"canon": {"x": 10}})

    def test_reverse_default_writes_none(self) -> None:
        plan = Plan(steps=(_failing_step(on_failure="default"),))
        result = plan.reverse({"canon": {"x": 10}})
        assert result == {"region": {"x": None}}


class TestLookups:
    def test_weight_of_known_and_unknown_path(self) -> None:
        plan = Plan(steps=(_identity_step(canonical="c", region="r", weight=5),))
        assert plan.weight_of("r") == 5
        assert plan.weight_of("nonexistent") == 0

    def test_is_declared_loss_and_note(self) -> None:
        step = Step(
            canonical_path="c",
            region_path="r",
            transform_chain=(TransformCall(name="identity", args={}),),
            disposition_status=None,
            on_failure="escalate",
            weight=3,
            reversible=True,
            declared_loss_kind="precision",
            note="a real note",
        )
        plan = Plan(steps=(step,))
        assert plan.is_declared_loss("r") is True
        assert plan.declared_loss_kind("r") == "precision"
        assert plan.note_of("r") == "a real note"
        assert plan.is_declared_loss("nonexistent") is False
        assert plan.declared_loss_kind("nonexistent") is None
        assert plan.note_of("nonexistent") is None
