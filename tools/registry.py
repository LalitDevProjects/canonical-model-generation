"""
The tool registry (Section 7.2): "Agents reach everything through typed
tools. The gateway holds the registry, enforces per-agent authorisation,
validates arguments and results against schema, and audits every call."

`ToolDefinition`'s own shape matches the spec's one fully-worked example
(acord.lookup, given as a complete JSON document) exactly:
name/description/input_schema/output_schema/authorisation/audit.
Authorisation is by explicit agent id list (`authorised_agents`), the
worked example's own representation - not the summary table's
"Discovery family" shorthand, which is less precise and would need every
future family member's id added as agents are built anyway. The one
exception is `authorised_agents="*"`, used only for the two tools the
summary table itself marks "All families" (`artefact.write`,
`substrate.query`... - Section 7.1's invoke() step 9 runs
`ctx.tools.write(...)` for every agent unconditionally, so hardcoding a
short, ever-growing explicit list for that one tool specifically would
be actively wrong, not just less precise.

Only 9 tools are named in Section 7.2's table. Of those, this repo
builds real handlers now for the ones Increment 6's own two agents
(Repository Scout, Schema Interpreter) or the already-real
`substrate/api.py::SubstrateApi` need with near-zero marginal cost:
`artefact.write` (the framework-level write every agent performs at
invoke() step 9), `spec.parse` (wraps parsers/router.py::parse -
Schema Interpreter), `substrate.query`/`substrate.neighbours`/
`acord.lookup` (thin wrappers over SubstrateApi, unblocks Increment 7/8
agents though neither of this increment's own agents calls them).
`repo.search`/`repo.read`/`kb.search`/`catalogue.query` are registered
(metadata only, per "every tool in 7.2 is specified this way in tools/")
but have no real handler yet - honestly deferred, not silently stubbed;
none of them would function without a real search index this repo
doesn't have.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    authorised_agents: list[str] | Literal["*"]
    """"*" means every agent (the spec's own "All families") - only used
    for artefact.write and substrate.query/neighbours, per this module's
    own docstring. Every other tool uses an explicit id list."""
    requires: str | None = None
    audit_log: list[str] = field(default_factory=lambda: ["caller", "at"])


_ARTEFACT_REF_ITEM = {
    "type": "object",
    "required": ["evref", "score"],
    "properties": {
        "evref": {"type": "string"},
        "title": {"type": "string"},
        "snippet": {"type": "string"},
        "score": {"type": "number"},
    },
}

TOOL_REGISTRY: dict[str, ToolDefinition] = {
    "artefact.write": ToolDefinition(
        name="artefact.write",
        description="Write one agent output payload to the run's artefact store.",
        input_schema={
            "type": "object",
            "required": ["kind", "payload"],
            "properties": {
                "kind": {"type": "string"},
                "payload": {"type": "object"},
            },
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "required": ["artefactRef"],
            "properties": {"artefactRef": {"type": "string"}},
        },
        # "All families, schema-validated" (Section 7.2) - every agent,
        # present and future, gets this one unconditionally (Section
        # 7.1's invoke() step 9 runs it for every Agent.invoke() call).
        authorised_agents="*",
        audit_log=["caller", "kind", "at"],
    ),
    "spec.parse": ToolDefinition(
        name="spec.parse",
        description="Parse one admitted artefact's redacted content into AttributeRecords "
        "(Comprehension; deterministic; no model call).",
        input_schema={
            "type": "object",
            "required": ["artefactId", "format"],
            "properties": {
                "artefactId": {"type": "string"},
                "format": {"type": "string"},
            },
            "additionalProperties": False,
        },
        output_schema={"type": "array", "items": {"type": "object"}},
        authorised_agents=["schema-interpreter"],
        audit_log=["caller", "artefactId", "at"],
    ),
    "substrate.query": ToolDefinition(
        name="substrate.query",
        description="Hybrid BM25 + vector search over the run's chunk index.",
        input_schema={
            "type": "object",
            "required": ["query"],
            "properties": {
                "query": {"type": "string"},
                "filters": {"type": "object"},
                "topK": {"type": "integer", "minimum": 1, "maximum": 100, "default": 25},
            },
            "additionalProperties": False,
        },
        output_schema={"type": "array", "items": _ARTEFACT_REF_ITEM},
        authorised_agents="*",  # "All families" per Section 7.2
        audit_log=["caller", "query", "at"],
    ),
    "substrate.neighbours": ToolDefinition(
        name="substrate.neighbours",
        description="Embedding neighbourhood over an attribute's name + description.",
        input_schema={
            "type": "object",
            "required": ["attributeId"],
            "properties": {
                "attributeId": {"type": "string"},
                "topK": {"type": "integer", "minimum": 1, "maximum": 100, "default": 25},
            },
            "additionalProperties": False,
        },
        output_schema={"type": "array", "items": {"type": "object"}},
        # Comprehension family (Section 7.2). Semantic Resolver's own
        # §7.5.1 spec names this tool in its declared tools list, so it's
        # authorised here for fidelity - Increment 7's own
        # SemanticResolverAgent doesn't call it through the gateway yet
        # (assemble_context reads via SubstrateApi.search directly, the
        # same "read the substrate, don't route a read through a tool
        # call" precedent Repository Scout already set for artefact
        # fields), same honest-but-unused status this tool already had
        # for Repository Scout/Schema Interpreter before this increment.
        authorised_agents=["schema-interpreter", "semantic-resolver"],
        audit_log=["caller", "attributeId", "at"],
    ),
    "acord.lookup": ToolDefinition(
        name="acord.lookup",
        description="Search the licensed ACORD reference pack for concepts matching a query.",
        input_schema={
            "type": "object",
            "required": ["query"],
            "properties": {
                "query": {"type": "string", "maxLength": 400},
                "model": {"enum": ["information", "data", "glossary", "ngds"]},
                "topK": {"type": "integer", "minimum": 1, "maximum": 25, "default": 10},
            },
            "additionalProperties": False,
        },
        output_schema={
            "type": "array",
            "items": {
                "type": "object",
                "required": ["acordRef", "entity", "definition", "score"],
                "properties": {
                    "acordRef": {"type": "string", "pattern": "^acord://"},
                    "entity": {"type": "string"},
                    "attribute": {"type": ["string", "null"]},
                    "definition": {"type": "string"},
                    "score": {"type": "number"},
                },
            },
        },
        authorised_agents=["acord-aligner", "canonical-synthesiser"],  # not yet built (Increment 8)
        requires="licence.disposition == permitted",
        audit_log=["caller", "query", "returnedRefs", "at"],
    ),
    "repo.search": ToolDefinition(
        name="repo.search",
        description="Search source repository content (needs a real search index - not built yet).",
        input_schema={
            "type": "object",
            "required": ["query", "repoIds"],
            "properties": {
                "query": {"type": "string"},
                "repoIds": {"type": "array", "items": {"type": "string"}},
                "pathGlob": {"type": "string"},
                "maxResults": {"type": "integer", "minimum": 1, "default": 25},
            },
            "additionalProperties": False,
        },
        output_schema={"type": "array", "items": _ARTEFACT_REF_ITEM},
        authorised_agents=["repository-scout"],
        audit_log=["caller", "query", "at"],
    ),
    "repo.read": ToolDefinition(
        name="repo.read",
        description="Read one pinned repository reference (needs real connector wiring - not built yet).",
        input_schema={
            "type": "object",
            "required": ["evref"],
            "properties": {"evref": {"type": "string"}},
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "required": ["content", "mediaType"],
            "properties": {"content": {"type": "string"}, "mediaType": {"type": "string"}},
        },
        authorised_agents=["repository-scout", "schema-interpreter"],
        audit_log=["caller", "evref", "at"],
    ),
    "kb.search": ToolDefinition(
        name="kb.search",
        description="Search knowledge-base content (needs a real search index - not built yet).",
        input_schema={
            "type": "object",
            "required": ["query"],
            "properties": {
                "query": {"type": "string"},
                "spaces": {"type": "array", "items": {"type": "string"}},
                "labels": {"type": "array", "items": {"type": "string"}},
                "topK": {"type": "integer", "minimum": 1, "default": 25},
            },
            "additionalProperties": False,
        },
        output_schema={"type": "array", "items": _ARTEFACT_REF_ITEM},
        authorised_agents=["repository-scout"],
        audit_log=["caller", "query", "at"],
    ),
    "catalogue.query": ToolDefinition(
        name="catalogue.query",
        description="Query the API catalogue (no catalogue connector exists yet - not built).",
        input_schema={
            "type": "object",
            "properties": {
                "domain": {"type": "string"},
                "region": {"type": "string"},
                "status": {"type": "string"},
            },
            "additionalProperties": False,
        },
        output_schema={"type": "array", "items": {"type": "object"}},
        authorised_agents=["repository-scout"],
        audit_log=["caller", "at"],
    ),
}
