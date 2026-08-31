# mapping

Populated at Increment 9. Section 10's mapping specification DSL: a
declarative, closed transform vocabulary for describing how one region's
contract relates to the canonical model - "not a general-purpose
scripting language, and not code" (Section 10.1).

- `transforms.py` - the 14-entry closed transform library (Section 10.3),
  each with a real forward and (where defined) reverse implementation.
  Every forward/reverse function shares one signature -
  `(value, **kwargs) -> Any` - so `mapping/interpreter.py::Plan` can
  dispatch generically in both directions. `coalesce` and `constant`
  (used as an entry's own top-level transform) have no reverse, matching
  the spec's own "Reverse is undefined" / "n/a" table entries.
- `parser.py` - parses a `transform:` string (Section 10.2's
  TransformExpr/TransformCall/ArgList grammar) into an ordered
  `TransformCall` chain. Enforces the 3-call chain limit. `constant(...)`
  used as a nested argument value (e.g. `currency=constant("GBP")`) is
  resolved to a plain literal at parse time; used as a call's own
  top-level name, its sole positional argument becomes the `const`
  keyword `transforms.py::_constant` expects.
- `compiler.py` - `compile_spec()`: Section 10.4's T1 (Totality), T2
  (weight rule), T3 (type fit), T4 (value-map completeness, plus its own
  injectivity check), and a builder-added D1 (a bidirectional entry may
  not use a transform with no reverse - needed because `Plan.reverse()`
  had to be designed from scratch, see `interpreter.py`). Every check is
  a build failure (`CompilationFailed`), never a warning. Resolves
  `valueMap` calls' `map` id against the spec's own `valueMaps` section
  at compile time, injecting the resolved dict into the compiled
  `TransformCall.args` so the interpreter needs no per-transform
  special-casing.
- `interpreter.py` - `class Plan`, the reference interpreter (Section
  10.6). `forward()` is transcribed from the spec's own pseudocode;
  `reverse()` is a real gap the spec never fills in (only referenced by
  Section 10.5's own pseudocode) - designed symmetrically here, applying
  each step's transforms' reverse callables in reverse chain order with
  the identical `on_failure` dispatch. The grammar defines no `default:`
  value field anywhere, so `onFailure: default` writes `None` - the only
  default value the DSL can express.
- `roundtrip.py` - `generate_round_trip_tests()` (Section 10.5):
  synthesises instances from region schema constraints (enumerations for
  real; other constraint expressions are a documented simplification,
  same status as `algorithms/naming.py`'s abbreviation table), runs
  forward then reverse, and raises `RoundTripFailure` if any *undeclared*
  loss occurs anywhere - "Declared losses are acceptable; undeclared ones
  are defects." `summarise()` produces the aggregate
  `{generated, assertion, declaredLosses, result}` shape Appendix C's own
  worked example uses for `contracts/C10/MappingSpec/1.0.json`'s `tests`
  field (a genuine contract gap this increment closed - see
  `docs/contracts.md`).

`config/settings.py::MappingConfig` (`round_trip_n=24`,
`critical_weight=5`) carries the two scalars Section 10.5's own pseudocode
hard-codes as defaults.

See `agents/mapping_generator.py` for the agent that proposes real
`MappingSpec` documents (Appendix B), and `emit/` for what consumes a
compiled plan's round-trip results into the workshop pack.
