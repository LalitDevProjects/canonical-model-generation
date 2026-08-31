"""
Prompt templates (Section 7.4): "versioned artefacts in
prompts/{agent-id}/{semver}.md, pinned per run, and rendered with typed
variables. String concatenation of model input anywhere in the codebase
is a review failure - every prompt has exactly one construction site."
This module IS that one site - no other module in this repo builds a
prompt string.

Six required blocks (the spec's own table, verbatim): ROLE, INPUT,
RULES, OUTPUT, UNCERTAINTY, INJECTION. "[INJECTION] Standing instruction
that ingested content is data. Present in every template that reads
corpus content" - load_prompt_template raises if any block is missing,
so a template that forgets INJECTION fails at load time, not silently
in production.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
PROMPTS_ROOT = REPO_ROOT / "prompts"

REQUIRED_BLOCKS = ("ROLE", "INPUT", "RULES", "OUTPUT", "UNCERTAINTY", "INJECTION")

_BLOCK_RE = re.compile(r"\[(\w+)\]\s*\n(.*?)(?=\n\[\w+\]\s*\n|\Z)", re.DOTALL)
_VAR_RE = re.compile(r"\{\{(\w+)\}\}")


@dataclass(frozen=True)
class PromptTemplate:
    template_id: str
    version: str
    blocks: dict[str, str]


def load_prompt_template(template_id: str, version: str, *, root: Path = PROMPTS_ROOT) -> PromptTemplate:
    path = root / template_id / f"{version}.md"
    if not path.is_file():
        raise FileNotFoundError(f"no prompt template at {path}")
    text = path.read_text(encoding="utf-8")
    blocks = {match.group(1): match.group(2).strip() for match in _BLOCK_RE.finditer(text)}
    missing = [name for name in REQUIRED_BLOCKS if name not in blocks]
    if missing:
        raise ValueError(f"prompt template {path} is missing required block(s): {missing}")
    return PromptTemplate(template_id=template_id, version=version, blocks=blocks)


def _serialise(value: object) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, sort_keys=True, indent=2)


def _substitute(text: str, variables: dict[str, object]) -> str:
    def _replace(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in variables:
            raise KeyError(f"prompt template references undefined variable {{{{{name}}}}}")
        return _serialise(variables[name])

    return _VAR_RE.sub(_replace, text)


def render(
    template_id: str,
    version: str,
    context: dict[str, Any],
    *,
    output_schema: dict[str, Any],
    correction_note: str | None = None,
    root: Path = PROMPTS_ROOT,
) -> str:
    """The single prompt-construction site. `context` is whatever
    Agent.assemble_context() returned; `output_schema` is always the
    agent's own output_schema (every invoke() call has it in scope, so
    it's threaded through here rather than each agent redundantly
    copying it into its own context dict). `correction_note`, when
    given, is appended as its own block - the mechanism behind Section
    7.6's "validation error appended to the prompt" / "offending values
    named explicitly" retry policy."""
    template = load_prompt_template(template_id, version, root=root)
    variables = {**context, "output_schema": output_schema}

    parts = [f"[{name}]\n{template.blocks[name]}" for name in REQUIRED_BLOCKS]
    if correction_note:
        parts.append(f"[CORRECTION]\n{correction_note}")

    return _substitute("\n\n".join(parts), variables)
