"""
Section 10.6's reference interpreter, `class Plan`. The spec shows
`forward()` in full but only ever *references* `reverse()` (from Section
10.5's own `generate_round_trip_tests()` pseudocode) without giving it a
body - a real gap, resolved here symmetrically: `reverse()` walks the same
steps, applies each transform's declared reverse callable
(mapping/transforms.py) in reverse chain order, and reuses the identical
on_failure dispatch (`_handle`).

Two further gaps in the spec's own literal text, both resolved and
documented at the point they matter:

- The grammar (Section 10.2) defines no `default:` field for an entry, so
  `onFailure: default` has no value anywhere in the DSL to write. This
  interpreter writes `None` - the only default value the grammar can
  express - and callers/tests treat that as the expected behaviour, not a
  bug.
- `_read`/`_write` support plain dot-delimited paths only. Appendix C's
  own worked example includes one array-shaped canonical path
  (`coveragesInForce[].limit`); this reference interpreter does not
  resolve `[]` array segments - out of scope for a PoC reference
  implementation whose round-trip generator only ever synthesises
  scalar-shaped instances (mapping/roundtrip.py).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from mapping.parser import TransformCall
from mapping.transforms import TRANSFORMS, TransformError

OnFailure = Literal["reject", "escalate", "default", "skip"]
DEFAULT_ON_FAILURE: OnFailure = "escalate"


class MappingRejected(Exception):
    """Raised when a `reject` step fails - Section 10.6: "what stops a
    mapping quietly producing an incomplete canonical instance." """

    def __init__(self, path: str | None, error: TransformError) -> None:
        super().__init__(f"mapping rejected at {path!r}: {error}")
        self.path = path
        self.error = error


@dataclass(frozen=True)
class Step:
    canonical_path: str | None
    region_path: str | None
    transform_chain: tuple[TransformCall, ...]
    disposition_status: str | None
    on_failure: OnFailure
    weight: int
    reversible: bool
    declared_loss_kind: str | None
    """None when this step carries no declared loss; otherwise "precision"
    (an SME-authored note on a lossy transform) or "undefined-reverse"
    (a structural loss - the chain contains a transform with no reverse)."""
    note: str | None


@dataclass(frozen=True)
class Escalation:
    step: Step
    error: TransformError


@dataclass
class Plan:
    steps: tuple[Step, ...]
    escalations: list[Escalation] = field(default_factory=list)

    def forward(self, region_instance: dict[str, Any]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for step in self.steps:
            if step.disposition_status is not None:
                continue
            try:
                value = read_path(region_instance, step.region_path)
                for call in step.transform_chain:
                    value = TRANSFORMS[call.name].forward(value, **call.args)
                write_path(out, step.canonical_path, value)
            except TransformError as err:
                self._handle(step, err, out, target=step.canonical_path)
        return out

    def reverse(self, canonical_instance: dict[str, Any]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for step in self.steps:
            if step.disposition_status is not None or not step.reversible:
                continue
            try:
                value = read_path(canonical_instance, step.canonical_path)
                for call in reversed(step.transform_chain):
                    spec = TRANSFORMS[call.name]
                    if spec.reverse is None:
                        raise TransformError(f"{call.name}: reverse is undefined")
                    value = spec.reverse(value, **call.args)
                write_path(out, step.region_path, value)
            except TransformError as err:
                self._handle(step, err, out, target=step.region_path)
        return out

    def _handle(self, step: Step, err: TransformError, out: dict[str, Any], target: str | None) -> None:
        if step.on_failure == "reject":
            raise MappingRejected(target, err)
        if step.on_failure == "escalate":
            self.escalations.append(Escalation(step=step, error=err))
        elif step.on_failure == "default":
            write_path(out, target, None)
        # "skip" writes nothing.

    def weight_of(self, region_path: str) -> int:
        for step in self.steps:
            if step.region_path == region_path:
                return step.weight
        return 0

    def is_declared_loss(self, region_path: str) -> bool:
        for step in self.steps:
            if step.region_path == region_path:
                return step.declared_loss_kind is not None
        return False

    def declared_loss_kind(self, region_path: str) -> str | None:
        for step in self.steps:
            if step.region_path == region_path:
                return step.declared_loss_kind
        return None

    def note_of(self, region_path: str) -> str | None:
        for step in self.steps:
            if step.region_path == region_path:
                return step.note
        return None


def read_path(instance: dict[str, Any], path: str | None) -> Any:
    if path is None:
        return None
    current: Any = instance
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def write_path(out: dict[str, Any], path: str | None, value: Any) -> None:
    if path is None:
        return
    parts = path.split(".")
    current = out
    for part in parts[:-1]:
        current = current.setdefault(part, {})
    current[parts[-1]] = value
