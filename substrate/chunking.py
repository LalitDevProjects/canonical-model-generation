"""
Chunking (Section 6.2). A lightweight, per-artefact-kind walk,
independent of parsers/ - same precedent as gate/structure.py: parsers/
exists to produce AttributeRecords (a different output shape/purpose),
and chunking needs to run over EVERY admitted artefact for retrieval,
not just ones a parser happens to be registered for.

Chunk identity is the SHA-256 of normalised content (Section 6.2's own
idempotency key - "re-ingesting an unchanged artefact produces identical
chunk hashes and skips the embedding call entirely"). Chunk evref follows
the existing evref://{region}/{system}/{artefactId}@{contentHash[:16]}#{locator}
convention from parsers/record_builder.py - not a new scheme.

Only the artefact kinds this repo has real fixtures/connectors for are
implemented: OpenAPI/JSON Schema, XSD, WSDL, Confluence. Source code and
the ACORD reference pack are confirmed out of scope (parsers/code_inference.py
is a stub; ACORD data is unlicensed). Avro is absent from Section 6.2's
own table entirely - chunk_avro's "one chunk per named record/enum/fixed"
rule is a documented builder default, the nearest analogue to the other
rows' "one chunk per named type" shape.

chunk() returns an empty list for a media type with no registered
chunker, rather than raising - a deliberate, more lenient divergence from
parsers/router.py::parse()'s raise-on-unknown behaviour: a missing
chunker should not fail an entire ingestion run, only omit that one
artefact's kind from retrieval coverage.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import yaml
from lxml import etree

from generated.C1.SourceArtefact._1_0 import C1Sourceartefact

_WSDL_NS = "http://schemas.xmlsoap.org/wsdl/"
_WSDL_ROOT_TAG = f"{{{_WSDL_NS}}}definitions"

_CONFLUENCE_MIN_TOKENS = 400
_CONFLUENCE_MAX_TOKENS = 900
_CONFLUENCE_OVERLAP_RATIO = 0.15


@dataclass(frozen=True)
class ChunkDraft:
    artefact_id: str
    content_hash: str
    evref: str
    region: str
    evidence_tier: int
    artefact_kind: str
    text: str
    chunk_hash: str


def compute_chunk_hash(text: str) -> str:
    """SHA-256 of normalised (whitespace-collapsed) content - Section
    6.2's literal idempotency key."""
    normalised = " ".join(text.split())
    return hashlib.sha256(normalised.encode("utf-8")).hexdigest()


def _draft(artefact: C1Sourceartefact, kind: str, text: str, *, locator: str) -> ChunkDraft:
    evref = (
        f"evref://{artefact.region.value}/{artefact.system.value}/"
        f"{artefact.artefactId}@{artefact.contentHash[:16]}#{locator}"
    )
    return ChunkDraft(
        artefact_id=artefact.artefactId,
        content_hash=artefact.contentHash,
        evref=evref,
        region=artefact.region.value,
        evidence_tier=artefact.evidenceTier,
        artefact_kind=kind,
        text=text,
        chunk_hash=compute_chunk_hash(text),
    )


# --- OpenAPI / JSON Schema -----------------------------------------------
# "One chunk per named schema component, with its $ref closure inlined to
# depth 1. A type is only interpretable together with the types it
# immediately references."

def _inline_refs_depth1(node: object, schemas: dict[str, object]) -> object:
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/components/schemas/"):
            target_name = ref.rsplit("/", 1)[-1]
            # Depth 1: the referenced schema's OWN body is inlined, but its
            # own $refs are left unresolved - not recursed into further.
            return {"$ref": ref, "$inlined": schemas.get(target_name)}
        return {key: _inline_refs_depth1(value, schemas) for key, value in node.items()}
    if isinstance(node, list):
        return [_inline_refs_depth1(item, schemas) for item in node]
    return node


def chunk_openapi(content: bytes, artefact: C1Sourceartefact) -> list[ChunkDraft]:
    document = yaml.safe_load(content) or {}
    schemas = ((document.get("components") or {}).get("schemas")) or {}
    drafts: list[ChunkDraft] = []
    for name, schema in schemas.items():
        inlined = _inline_refs_depth1(schema, schemas)
        text = f"{name}\n{json.dumps(inlined, sort_keys=True, indent=2)}"
        drafts.append(_draft(artefact, "openapi", text, locator=f"components/schemas/{name}"))
    return drafts


# --- XSD / WSDL -----------------------------------------------------------
# "One chunk per complex type or operation, with inherited members
# inlined. Same reasoning; inheritance must travel with the type."

def _qname(node: Any) -> str:
    """Empty string for a comment/processing-instruction node (lxml gives
    those a callable, not a string, .tag) - never matches a real tag
    name, so every `_qname(node) == "..."` comparison below safely skips
    them without each caller needing its own isinstance guard. The
    golden XSD fixture has top-level <!-- ... --> comments, which a
    blind `for node in root: etree.QName(node)` would otherwise raise
    on."""
    if not isinstance(node.tag, str):
        return ""
    return str(etree.QName(node).localname)


def _strip_prefix(qname: str | None) -> str | None:
    if qname is None:
        return None
    return qname.split(":", 1)[-1]


def _child(node: Any, tag: str) -> Any | None:
    for candidate in node:
        if _qname(candidate) == tag:
            return candidate
    return None


def _collect_direct_members(node: Any) -> list[str]:
    members: list[str] = []
    sequence = _child(node, "sequence")
    container = sequence if sequence is not None else node
    for child in container:
        tag = _qname(child)
        if tag == "element":
            name = child.get("name")
            type_name = _strip_prefix(child.get("type")) or "?"
            flags = []
            if child.get("nillable") == "true":
                flags.append("nillable")
            if child.get("minOccurs") == "0":
                flags.append("optional")
            suffix = f" [{', '.join(flags)}]" if flags else ""
            members.append(f"{name}: {type_name}{suffix}")
        elif tag == "choice":
            branch_names = [c.get("name") for c in child if _qname(c) == "element" and c.get("name")]
            members.append(f"choice({child.get('id') or ''}): {', '.join(branch_names)}")
    for child in node:
        if _qname(child) == "attribute":
            name = child.get("name")
            type_name = _strip_prefix(child.get("type")) or "?"
            required = " [required]" if child.get("use") == "required" else ""
            members.append(f"@{name}: {type_name}{required}")
    return members


def _collect_members(complex_type_node: Any, complex_types: dict[str, Any]) -> list[str]:
    """xs:extension flattening (Section 4.4): a base type's own members
    are inlined ahead of the extension's own, matching parsers/xsd.py's
    "Flattened with inherited members" idiom - same reasoning, applied
    here for retrievable text rather than AttributeRecords."""
    complex_content = _child(complex_type_node, "complexContent")
    if complex_content is not None:
        extension = _child(complex_content, "extension")
        if extension is not None:
            base_name = _strip_prefix(extension.get("base"))
            base_node = complex_types.get(base_name) if base_name else None
            inherited = _collect_members(base_node, complex_types) if base_node is not None else []
            return inherited + _collect_direct_members(extension)
    return _collect_direct_members(complex_type_node)


def chunk_xsd(content: bytes, artefact: C1Sourceartefact) -> list[ChunkDraft]:
    root = etree.fromstring(content)
    complex_types: dict[str, Any] = {}
    for node in root:
        if _qname(node) == "complexType":
            name = node.get("name")
            if name:
                complex_types[name] = node

    drafts: list[ChunkDraft] = []
    for node in root:
        tag = _qname(node)
        if tag == "complexType":
            name = node.get("name")
            if name:
                text = name + "\n" + "\n".join(_collect_members(node, complex_types))
                drafts.append(_draft(artefact, "xsd", text, locator=f"complexType/{name}"))
        elif tag == "element":
            name = node.get("name")
            inline_complex_type = _child(node, "complexType")
            if name and inline_complex_type is not None:
                text = name + "\n" + "\n".join(_collect_members(inline_complex_type, complex_types))
                drafts.append(_draft(artefact, "xsd", text, locator=f"element/{name}"))
    return drafts


def chunk_wsdl(content: bytes, artefact: C1Sourceartefact) -> list[ChunkDraft]:
    """One chunk per wsdl:operation - the embedded xs:schema's own
    complex types are NOT re-chunked here (that would duplicate the
    identical content whenever the same schema also appears as a
    standalone .xsd artefact, as it does in the golden corpus); a WSDL
    artefact's own chunking unit is its operations."""
    root = etree.fromstring(content)
    drafts: list[ChunkDraft] = []
    for operation in root.iter(f"{{{_WSDL_NS}}}operation"):
        name = operation.get("name")
        if not name:
            continue
        parts = [
            f"{_qname(child)}: {_strip_prefix(child.get('message'))}"
            for child in operation
            if child.get("message") is not None
        ]
        text = name + "\n" + "\n".join(parts)
        drafts.append(_draft(artefact, "wsdl", text, locator=f"operation/{name}"))
    return drafts


def _chunk_xml(content: bytes, artefact: C1Sourceartefact) -> list[ChunkDraft]:
    """application/xml is shared by .xsd and .wsdl (connectors/git_connector.py's
    extension table) - disambiguated by root element tag, same approach
    as parsers/router.py::_dispatch_xml."""
    root_tag = etree.fromstring(content).tag
    if root_tag == _WSDL_ROOT_TAG:
        return chunk_wsdl(content, artefact)
    return chunk_xsd(content, artefact)


# --- Confluence / Jira ------------------------------------------------
# "Semantic split on heading boundaries, 400-900 tokens, 15% overlap.
# Headings are the author's own topic boundaries and beat any fixed
# window." A regex-based split, not a real HTML parser - same honesty
# standard as connectors/confluence_connector.py's own _strip_tags
# ("good enough for a short description preview; not a real HTML
# parser"). "Tokens" here means whitespace-delimited words, a documented
# PoC simplification, not a real tokenizer.

_HEADING_RE = re.compile(r"<h[1-6][^>]*>(.*?)</h[1-6]>", re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")


def _strip_tags(html: str) -> str:
    return _TAG_RE.sub(" ", html)


def _split_on_headings(html: str) -> list[tuple[str, str]]:
    matches = list(_HEADING_RE.finditer(html))
    if not matches:
        body = _strip_tags(html).strip()
        return [("", body)] if body else []
    sections: list[tuple[str, str]] = []
    for index, match in enumerate(matches):
        heading = _strip_tags(match.group(1)).strip()
        body_start = match.end()
        body_end = matches[index + 1].start() if index + 1 < len(matches) else len(html)
        body = _strip_tags(html[body_start:body_end]).strip()
        sections.append((heading, body))
    return sections


def _split_by_token_budget(text: str, *, max_tokens: int, overlap_ratio: float) -> list[str]:
    words = text.split()
    if len(words) <= max_tokens:
        return [text] if words else []
    step = max(1, int(max_tokens * (1 - overlap_ratio)))
    pieces: list[str] = []
    start = 0
    while start < len(words):
        end = min(start + max_tokens, len(words))
        pieces.append(" ".join(words[start:end]))
        if end == len(words):
            break
        start += step
    return pieces


def _slug(text: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower() or "section"


def chunk_confluence(content: bytes, artefact: C1Sourceartefact) -> list[ChunkDraft]:
    html = content.decode("utf-8")
    drafts: list[ChunkDraft] = []
    for heading, body in _split_on_headings(html):
        pieces = _split_by_token_budget(body, max_tokens=_CONFLUENCE_MAX_TOKENS, overlap_ratio=_CONFLUENCE_OVERLAP_RATIO)
        for piece_index, piece in enumerate(pieces):
            text = f"{heading}\n{piece}" if heading else piece
            locator = f"heading/{_slug(heading)}" + (f"/{piece_index}" if len(pieces) > 1 else "")
            drafts.append(_draft(artefact, "confluence", text, locator=locator))
    return drafts


# --- Avro (absent from Section 6.2's table; a documented builder default) -

def _walk_avro_named_types(node: object, artefact: C1Sourceartefact, drafts: list[ChunkDraft]) -> None:
    if isinstance(node, dict):
        node_type = node.get("type")
        name = node.get("name")
        if node_type in ("record", "enum", "fixed") and isinstance(name, str):
            text = f"{name}\n{json.dumps(node, sort_keys=True, indent=2)}"
            drafts.append(_draft(artefact, "avro", text, locator=f"{node_type}/{name}"))
        for value in node.values():
            _walk_avro_named_types(value, artefact, drafts)
    elif isinstance(node, list):
        for item in node:
            _walk_avro_named_types(item, artefact, drafts)


def chunk_avro(content: bytes, artefact: C1Sourceartefact) -> list[ChunkDraft]:
    document = json.loads(content)
    drafts: list[ChunkDraft] = []
    _walk_avro_named_types(document, artefact, drafts)
    return drafts


# --- Dispatch ---------------------------------------------------------

ChunkerFn = Callable[[bytes, C1Sourceartefact], list[ChunkDraft]]

_CHUNKERS: dict[str, ChunkerFn] = {
    "application/vnd.oai.openapi": chunk_openapi,
    "application/yaml": chunk_openapi,
    "application/x-yaml": chunk_openapi,
    "application/json": chunk_openapi,
    "application/schema+json": chunk_openapi,
    "application/xml": _chunk_xml,
    "application/vnd.apache.avro+json": chunk_avro,
    "application/vnd.atlassian.confluence.storage+xml": chunk_confluence,
}


def chunk(content: bytes, artefact: C1Sourceartefact) -> list[ChunkDraft]:
    media_type = artefact.mediaType
    chunker = _CHUNKERS.get(media_type) if media_type else None
    if chunker is None:
        return []
    return chunker(content, artefact)
