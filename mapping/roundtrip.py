"""
Section 10.5's `generate_round_trip_tests()`, transcribed against this
repo's real `Plan`/`Step` shapes (mapping/interpreter.py).

`synthesise_instance()` honours enumerations (Section 10.5: "Instances are
generated from schema constraints, not sampled from real data") but not
arbitrary pattern/range constraint expressions - Section 5's own
AttributeRecord.constraints carries free-text `expression` strings with no
declared grammar (the same "no exhaustive spec" status as
`algorithms/naming.py`'s abbreviation table), so generating a value
provably satisfying an arbitrary expression is out of scope for a PoC
reference generator. Dates/dateTimes are synthesised in ISO-8601
(`YYYY-MM-DD` / `YYYY-MM-DDTHH:MM:SS`), the convention every worked
`fmt` in this repo's own fixtures (transcribed from Appendix C) already
expects.

The one place this module's design deliberately diverges from Section
10.5's own literal pseudocode: that pseudocode computes each `TestCase`'s
own `passed` as `not critical_losses`, where `critical_losses` are ALL
weight>=5 losses regardless of whether they are declared. Applied
literally, Appendix C's own worked example would have to report
`result: fail` - its one loss (`ClaimHeader.LossDate`) is both weight 5
AND declared, yet the worked example's own `tests.roundTrip.result` is
"pass". The spec's own governing prose settles this in the other
direction ("Declared losses are acceptable; undeclared ones are
defects" - Section 10.5) and the final gate the pseudocode itself uses
(`if any(c.undeclared_losses for c in cases): raise RoundTripFailure`)
already only inspects `undeclared_losses`. `passed`/`result` here are
computed against undeclared losses only, matching the worked example and
that governing prose over the one inconsistent pseudocode line.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from generated.C5.AttributeRecord._1_0 import C5Attributerecord
from mapping.interpreter import Plan, Step, read_path, write_path

DEFAULT_N = 24
CRITICAL_WEIGHT = 5


class RoundTripFailure(Exception):
    """An undeclared loss anywhere fails emission (Section 8.1's S8 exit criterion)."""

    def __init__(self, cases: list["TestCase"]) -> None:
        failing = [c for c in cases if c.undeclared_losses]
        super().__init__(f"{len(failing)}/{len(cases)} round-trip case(s) carry an undeclared loss")
        self.cases = cases


@dataclass(frozen=True)
class Loss:
    path: str
    weight: int
    declared: bool
    kind: str | None


@dataclass(frozen=True)
class TestCase:
    seed: int
    assertion: str
    passed: bool
    declared_losses: list[Loss]
    undeclared_losses: list[Loss]


ASSERTION = "no attribute with weight >= 5 is lost region -> canonical -> region"


def synthesise_instance(region_ir: list[C5Attributerecord], seed: int) -> dict[str, Any]:
    instance: dict[str, Any] = {}
    for rec in region_ir:
        write_path(instance, rec.path, _synth_value(rec, seed))
    return instance


def _synth_value(rec: C5Attributerecord, seed: int) -> Any:
    if rec.enumeration:
        return rec.enumeration[seed % len(rec.enumeration)].value
    data_type = rec.dataType.value
    if data_type == "date":
        return (date(2020, 1, 1) + timedelta(days=seed)).isoformat()
    if data_type == "dateTime":
        return (datetime(2020, 1, 1) + timedelta(days=seed, hours=seed % 24)).isoformat()
    if data_type == "integer":
        return seed + 1
    if data_type == "decimal":
        return round(seed + 1.5, 2)
    if data_type == "boolean":
        return seed % 2 == 0
    return f"{rec.localName}-{seed}"


def diff_attributes(instance: dict[str, Any], back: dict[str, Any], plan: Plan) -> list[Loss]:
    losses: list[Loss] = []
    for step in plan.steps:
        if step.disposition_status is not None or step.region_path is None:
            continue
        original = read_path(instance, step.region_path)
        recovered = read_path(back, step.region_path)
        if original != recovered:
            losses.append(
                Loss(
                    path=step.region_path,
                    weight=step.weight,
                    declared=step.declared_loss_kind is not None,
                    kind=step.declared_loss_kind,
                )
            )
    return losses


def generate_round_trip_tests(
    plan: Plan, region_ir: list[C5Attributerecord], n: int = DEFAULT_N
) -> list[TestCase]:
    cases: list[TestCase] = []
    for seed in range(n):
        instance = synthesise_instance(region_ir, seed)
        canonical = plan.forward(instance)
        back = plan.reverse(canonical)
        losses = diff_attributes(instance, back, plan)
        declared = [loss for loss in losses if loss.declared]
        undeclared = [loss for loss in losses if not loss.declared]
        cases.append(
            TestCase(
                seed=seed,
                assertion=ASSERTION,
                passed=not any(loss.weight >= CRITICAL_WEIGHT for loss in undeclared),
                declared_losses=declared,
                undeclared_losses=undeclared,
            )
        )
    if any(case.undeclared_losses for case in cases):
        raise RoundTripFailure(cases)
    return cases


def summarise(cases: list[TestCase], plan: Plan) -> dict[str, Any]:
    """Matches Appendix C's own `tests.roundTrip` worked shape - an
    aggregate summary of the whole generated run, deduped by path, not one
    row per synthesised seed.

    declaredLosses is sourced from the plan's own steps
    (declared_loss_kind), not from cases' empirical per-seed diffs: a
    structural loss (e.g. instantAtStartOfDay discarding a time-of-day
    that a plain `date`-typed source never carried in the first place) is
    a known property of the mapping itself, and may never actually show
    up as an observed diff for any synthesised seed - Appendix C's own
    worked LossDate example is exactly this case. What synthesised data
    can and does prove is the absence of any *undeclared* loss (result,
    below), which is the actual S8 gate."""
    declared_losses: list[dict[str, Any]] = [
        {"path": step.region_path, "kind": step.declared_loss_kind, "detail": _detail_for_step(step)}
        for step in plan.steps
        if step.declared_loss_kind is not None and step.region_path is not None
    ]
    result = "fail" if any(case.undeclared_losses for case in cases) else "pass"
    return {
        "generated": len(cases),
        "assertion": ASSERTION,
        "declaredLosses": declared_losses,
        "result": result,
    }


def _detail_for_step(step: Step) -> str:
    # mapping/compiler.py::_build_plan only ever sets declared_loss_kind to
    # "precision" alongside a real e.note, or to "undefined-reverse" (which
    # may or may not carry a note) - so the only kind reaching this
    # function without step.note is "undefined-reverse".
    if step.note:
        return step.note
    return "the transform chain for this entry has no reverse; the field does not round-trip"
