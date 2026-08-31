"""
Parses a C10 MappingSpec entry's `transform` string (Section 10.2's
TransformExpr/TransformCall/ArgList grammar) into an ordered list of
TransformCall objects mapping/interpreter.py::Plan can execute.

This is a small, hand-rolled scanner, not a generated parser - the
grammar is deliberately tiny (Section 10.1: "not a general-purpose
scripting language, and not code"), and every construct in it appears in
Appendix C's own worked example, which this module is built to parse
byte-for-byte:
    parseDate(fmt='yyyy-MM-dd') -> instantAtStartOfDay(zone='Europe/London')
    valueMap(map="ClaimStatus.uk")
    toMonetaryAmount(currency=constant("GBP"))
    identity

ArgList value literals are not given a sub-grammar anywhere in Section
10.2; this module resolves that gap by accepting quoted strings (both
' and "), bare integers/decimals, true/false, and unquoted bare tokens
(treated as literal strings) - covering every value shape Appendix C
actually uses.

`constant(...)` is handled two ways, matching the judgment call recorded
in the Increment 9 plan: as a call's own top-level name (`transform:
constant("GBP")`), its sole positional argument is normalised to the
`const` keyword mapping/transforms.py::_constant expects. As a *nested*
argument value (`currency=constant("GBP")`), it is resolved directly to
the literal "GBP" at parse time - a plain value-literal wrapper, not an
invocation of the constant transform.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

MAX_CHAIN_LENGTH = 3

_CALL_PATTERN = re.compile(r"^([A-Za-z_]\w*)\s*(\((.*)\))?$", re.DOTALL)
_KWARG_PATTERN = re.compile(r"^([A-Za-z_]\w*)\s*=\s*(.+)$", re.DOTALL)
_CONSTANT_WRAPPER_PATTERN = re.compile(r"^constant\((.*)\)$", re.DOTALL)
_INTEGER_PATTERN = re.compile(r"^-?\d+$")
_DECIMAL_PATTERN = re.compile(r"^-?\d+\.\d+$")


class MappingParseError(Exception):
    """Raised when a `transform:` string does not conform to Section 10.2's grammar."""


@dataclass(frozen=True)
class TransformCall:
    name: str
    args: dict[str, Any]


def parse_transform_expr(expr: str) -> list[TransformCall]:
    call_strs = [c.strip() for c in _split_top_level(expr, " -> ")]
    if len(call_strs) > MAX_CHAIN_LENGTH:
        raise MappingParseError(
            f"transform chain has {len(call_strs)} calls, exceeding the 3-call limit: {expr!r}"
        )
    return [_parse_call(c) for c in call_strs]


def _parse_call(call_str: str) -> TransformCall:
    match = _CALL_PATTERN.match(call_str)
    if match is None:
        raise MappingParseError(f"malformed transform call: {call_str!r}")
    name = match.group(1)
    args_str = match.group(3)
    args: dict[str, Any] = {}
    positional_used = False
    if args_str is not None and args_str.strip():
        for token in _split_top_level(args_str, ","):
            arg_name, value = _parse_arg(token)
            if arg_name is not None:
                args[arg_name] = value
            elif name == "constant" and not positional_used:
                args["const"] = value
                positional_used = True
            else:
                raise MappingParseError(
                    f"positional arguments are only supported for constant(...): {call_str!r}"
                )
    return TransformCall(name=name, args=args)


def _parse_arg(token: str) -> tuple[str | None, Any]:
    token = token.strip()
    if not token:
        raise MappingParseError("empty argument in transform call")
    kwarg_match = _KWARG_PATTERN.match(token)
    if kwarg_match:
        return kwarg_match.group(1), _parse_value(kwarg_match.group(2).strip())
    return None, _parse_value(token)


def _parse_value(token: str) -> Any:
    token = token.strip()
    const_match = _CONSTANT_WRAPPER_PATTERN.match(token)
    if const_match:
        return _parse_value(const_match.group(1).strip())
    if len(token) >= 2 and token[0] == token[-1] and token[0] in ("'", '"'):
        return token[1:-1]
    if _INTEGER_PATTERN.fullmatch(token):
        return int(token)
    if _DECIMAL_PATTERN.fullmatch(token):
        return float(token)
    if token in ("true", "false"):
        return token == "true"
    return token


def _split_top_level(text: str, separator: str) -> list[str]:
    """Splits on `separator` at bracket/quote depth 0. `separator` may be
    multi-character (e.g. the chain arrow ' -> '); a comma/arrow inside a
    quoted string or inside a nested constant(...) call is not a split
    point."""
    parts: list[str] = []
    current: list[str] = []
    depth = 0
    quote: str | None = None
    i = 0
    n = len(text)
    sep_len = len(separator)
    while i < n:
        ch = text[i]
        if quote is not None:
            current.append(ch)
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch in ("'", '"'):
            quote = ch
            current.append(ch)
            i += 1
            continue
        if ch == "(":
            depth += 1
            current.append(ch)
            i += 1
            continue
        if ch == ")":
            depth -= 1
            current.append(ch)
            i += 1
            continue
        if depth == 0 and text[i : i + sep_len] == separator:
            parts.append("".join(current))
            current = []
            i += sep_len
            continue
        current.append(ch)
        i += 1
    parts.append("".join(current))
    return parts
