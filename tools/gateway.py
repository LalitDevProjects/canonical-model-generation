"""
The tool gateway (Section 7.2): "An agent that requests a tool outside
its allow-list receives an error, and the attempt is journalled as a
tool.denied event - which is also the signal that would surface a
successful prompt injection." Authorisation, argument/result schema
validation, and audit journalling all happen here, in one place, so no
agent can reach a tool's real handler without passing through this gate.

ToolGateway.call() takes explicit run_id/agent_id rather than a full
RunContext (defined in agents/base.py) specifically to avoid a circular
import: agents/base.py needs ToolGateway for RunContext's own `tools`
field, so tools/gateway.py must not need agents/base.py in return.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import jsonschema

from generated.C1.SourceArtefact._1_0 import C1Sourceartefact
from generated.C5.AttributeRecord._1_0 import C5Attributerecord
from generated.C11.JournalEvent._1_0 import C11Journalevent

from pipeline.run_store import RunStore
from substrate.api import SubstrateApi
from tools.registry import TOOL_REGISTRY

HandlerFn = Callable[[dict[str, Any], "ToolGateway"], object]

ArtefactResolver = Callable[[str], tuple[bytes, C1Sourceartefact]]
"""artefactId -> (redacted content, its C1Sourceartefact) - how
spec.parse's handler gets real bytes to parse without exposing raw bytes
through the tool's own JSON-Schema-validated args (spec.parse's input
schema is exactly {artefactId, format}, matching Section 7.2's table
literally; the resolver is gateway-level wiring, not part of the tool's
public contract)."""


class ToolDenied(Exception):
    def __init__(self, agent_id: str, tool_name: str, reason: str) -> None:
        super().__init__(f"{agent_id!r} is not authorised to call {tool_name!r}: {reason}")
        self.agent_id = agent_id
        self.tool_name = tool_name
        self.reason = reason


def _handle_artefact_write(args: dict[str, Any], gateway: "ToolGateway") -> dict[str, Any]:
    artefact_ref = gateway.record_write(str(args["kind"]), dict(args["payload"]))
    return {"artefactRef": artefact_ref}


def _handle_spec_parse(args: dict[str, Any], gateway: "ToolGateway") -> list[dict[str, Any]]:
    from parsers.router import parse as parse_artefact

    content, source_artefact = gateway.resolve_artefact(str(args["artefactId"]))
    records: list[C5Attributerecord] = parse_artefact(content, source_artefact, gateway.run_id_for_parse)
    return [record.model_dump(mode="json") for record in records]


def _handle_substrate_query(args: dict[str, Any], gateway: "ToolGateway") -> list[dict[str, Any]]:
    chunks = gateway.substrate.search(
        str(gateway.run_id_for_parse), str(args["query"]), top_k=int(args.get("topK", 25)),
    )
    return [
        {"evref": c.evref, "title": c.artefact_id, "snippet": c.text[:280], "score": c.score}
        for c in chunks
    ]


def _handle_substrate_neighbours(args: dict[str, Any], gateway: "ToolGateway") -> list[dict[str, Any]]:
    records = gateway.substrate.neighbours(
        str(gateway.run_id_for_parse), str(args["attributeId"]), top_k=int(args.get("topK", 25)),
    )
    return [record.model_dump(mode="json") for record in records]


def _handle_acord_lookup(args: dict[str, Any], gateway: "ToolGateway") -> list[dict[str, Any]]:
    concepts = gateway.substrate.acord_lookup(
        str(gateway.run_id_for_parse), str(args["query"]), top_k=int(args.get("topK", 10)),
    )
    return [
        {"acordRef": f"acord://{c.acord_ref}", "entity": c.entity, "attribute": c.attribute, "definition": "", "score": 0.0}
        for c in concepts
    ]


_DEFAULT_HANDLERS: dict[str, HandlerFn] = {
    "artefact.write": _handle_artefact_write,
    "spec.parse": _handle_spec_parse,
    "substrate.query": _handle_substrate_query,
    "substrate.neighbours": _handle_substrate_neighbours,
    "acord.lookup": _handle_acord_lookup,
}


@dataclass
class ToolGateway:
    run_store: RunStore
    run_id_for_parse: UUID
    """The run_id real handlers (spec.parse's parser call, substrate.*'s
    SubstrateApi calls) need as their own argument - distinct from the
    run_id passed to .call()/.write() per invocation, which is only used
    for journalling. In practice these are the same UUID for a real run;
    kept as two named things because the journal's run_id is a genuine
    per-call argument (Section 7.1's ctx.run_id) while handlers close
    over the gateway's own construction-time run_id."""
    substrate_api: SubstrateApi | None = None
    artefact_resolver: ArtefactResolver | None = None
    handlers: dict[str, HandlerFn] = field(default_factory=lambda: dict(_DEFAULT_HANDLERS))
    _written: list[dict[str, Any]] = field(default_factory=list, repr=False)

    @property
    def substrate(self) -> SubstrateApi:
        if self.substrate_api is None:
            raise RuntimeError("this ToolGateway has no SubstrateApi configured")
        return self.substrate_api

    @property
    def written(self) -> list[dict[str, Any]]:
        return list(self._written)

    def resolve_artefact(self, artefact_id: str) -> tuple[bytes, C1Sourceartefact]:
        if self.artefact_resolver is None:
            raise RuntimeError("this ToolGateway has no artefact_resolver configured")
        return self.artefact_resolver(artefact_id)

    def record_write(self, kind: str, payload: dict[str, Any]) -> str:
        self._written.append({"kind": kind, "payload": payload})
        return f"artefact://{kind}/{len(self._written)}"

    def call(self, agent_id: str, tool_name: str, args: dict[str, Any], run_id: UUID) -> object:
        definition = TOOL_REGISTRY.get(tool_name)
        if definition is None:
            raise ToolDenied(agent_id, tool_name, "no such tool")

        authorised = definition.authorised_agents == "*" or agent_id in definition.authorised_agents
        if not authorised:
            self._journal(
                run_id, "tool.denied", agent_id=agent_id, tool=tool_name,
                outcome="failed", detail=f"{agent_id!r} is not authorised for {tool_name!r}",
            )
            raise ToolDenied(agent_id, tool_name, "not authorised")

        jsonschema.validate(args, definition.input_schema)

        handler = self.handlers.get(tool_name)
        if handler is None:
            raise NotImplementedError(f"tool {tool_name!r} is registered but has no real handler yet")
        result = handler(args, self)

        jsonschema.validate(result, definition.output_schema)
        self._journal(run_id, "tool.call", agent_id=agent_id, tool=tool_name, outcome="ok")
        return result

    def write(self, agent_id: str, run_id: UUID, payload: dict[str, Any]) -> object:
        """Section 7.1 invoke() step 9: `ctx.tools.write(self.agent_id, output)` -
        every agent performs this, not just ones that explicitly declare
        artefact.write in their own allow-list; it's the framework's own
        write path, wrapping the artefact.write tool."""
        return self.call(agent_id, "artefact.write", {"kind": agent_id, "payload": payload}, run_id)

    def _journal(
        self, run_id: UUID, kind: str, *, agent_id: str, tool: str, outcome: str, detail: str | None = None,
    ) -> None:
        event = C11Journalevent.model_validate({
            "runId": run_id,
            "seq": self.run_store.next_journal_seq(run_id),
            "at": datetime.now(timezone.utc),
            "kind": kind,
            "agent": agent_id,
            "tool": tool,
            "outcome": outcome,
            "detail": detail,
        })
        self.run_store.append_journal_event(run_id, event)
