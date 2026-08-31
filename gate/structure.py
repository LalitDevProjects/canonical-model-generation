"""
A lightweight structural walk of fetched content, independent of
`parsers/` even though it shares the same general traversal shape.

Two reasons this is its own thing, not a reuse of parsers/openapi.py or
parsers/xsd.py: (1) the gate runs during S1, before an artefact is known
to be kept at all - `parsers/` only ever runs later, on KEPT artefacts,
per Increment 3's own design; (2) parsers/ exists to produce
AttributeRecords, a different output shape/purpose entirely - it doesn't
currently record example/default VALUES anywhere (only enumeration
values), which is exactly what L3 needs. Re-purposing it would couple two
unrelated concerns for no real benefit given how thin each walk is.

This module classifies text by WHERE it sits in the document, into three
buckets:
  - structural_texts: grammar-position markers (L0) - dict keys, XSD
    element/type names, JSON-Schema keyword names
  - example_texts: literals reachable under example/examples/default/const
    (L3) - Section 4.4's "any literal appearing in example, examples,
    default, const, enum description text or a test fixture"
  - prose_texts: everything else free-text (description values, XSD
    xs:documentation, or - for content with no structural parser at all,
    e.g. Confluence's storage-format XHTML - the entire body) - this is
    what L1/L2/L4 actually scan for embedded PII/entities/lexicon terms

Redaction (gate/tokenisation.py) works by matching TEXT VALUES, not
document paths - so this module deliberately does not track byte offsets
or structural paths, only extracted strings. This keeps redaction a
simple, format-preserving substring replace over the ORIGINAL raw bytes
(no re-serialization, no formatting drift), at the cost of a theoretical
(and here, irrelevant) risk that a flagged literal also happens to appear
verbatim somewhere it shouldn't be redacted.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

import yaml
from lxml import etree

_XS_NS = "http://www.w3.org/2001/XMLSchema"
_WSDL_NS = "http://schemas.xmlsoap.org/wsdl/"

_EXAMPLE_KEYS = {"example", "examples", "default", "const"}
_PROSE_KEYS = {"description", "summary", "title"}
_STRUCTURAL_VALUE_KEYS = {"name", "type"}
"""String VALUES under these keys are themselves grammar-position markers
- a type declaration's value ("string", "object") or a field/element name
("claimId") - not just the key that introduces them. Without this, Avro's
{"name": "claimId", "type": "string"} would only ever record "name"/"type"
as structural and silently miss the actual identifier/type-keyword
values, since Avro (unlike OpenAPI, where property names are dict keys)
carries them as plain string VALUES."""

_JSON_LIKE_MEDIA_TYPES = {
    "application/vnd.oai.openapi",
    "application/yaml",
    "application/x-yaml",
    "application/json",
    "application/schema+json",
}
_XML_MEDIA_TYPES = {"application/xml"}
_AVRO_MEDIA_TYPE = "application/vnd.apache.avro+json"


@dataclass(frozen=True)
class ParsedDocument:
    kind: Literal["json_like", "xml", "avro", "none"]
    structural_texts: list[str] = field(default_factory=list)
    example_texts: list[str] = field(default_factory=list)
    prose_texts: list[str] = field(default_factory=list)


def parse_structure(content: bytes, media_type: str) -> ParsedDocument:
    if media_type in _JSON_LIKE_MEDIA_TYPES:
        try:
            document = yaml.safe_load(content)
        except yaml.YAMLError:
            return _whole_body_prose(content)
        result = ParsedDocument(kind="json_like")
        _walk_json_like(document, result)
        return result

    if media_type in _XML_MEDIA_TYPES:
        try:
            root = etree.fromstring(content)
        except etree.XMLSyntaxError:
            return _whole_body_prose(content)
        result = ParsedDocument(kind="xml")
        _walk_xml(root, result)
        return result

    if media_type == _AVRO_MEDIA_TYPE:
        try:
            document = yaml.safe_load(content)
        except yaml.YAMLError:
            return _whole_body_prose(content)
        result = ParsedDocument(kind="avro")
        _walk_json_like(document, result)
        return result

    return _whole_body_prose(content)


def _whole_body_prose(content: bytes) -> ParsedDocument:
    """No structural parser for this media type (e.g. Confluence's
    storage-format XHTML) - the entire body is treated as prose, scanned
    by L1/L2/L4 in full."""
    return ParsedDocument(kind="none", prose_texts=[content.decode("utf-8", errors="replace")])


def _walk_json_like(node: Any, result: ParsedDocument) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            if isinstance(key, str):
                result.structural_texts.append(key)
            if key in _EXAMPLE_KEYS:
                _collect_example_values(value, result)
            elif key in _PROSE_KEYS and isinstance(value, str):
                result.prose_texts.append(value)
            elif key in _STRUCTURAL_VALUE_KEYS and isinstance(value, str):
                result.structural_texts.append(value)
            else:
                _walk_json_like(value, result)
    elif isinstance(node, list):
        for item in node:
            _walk_json_like(item, result)
    # scalars (str/int/float/bool/None) reached outside a recognised key
    # contribute nothing on their own - they're only meaningful in
    # context of the key that held them, already handled above.


def _collect_example_values(node: Any, result: ParsedDocument) -> None:
    if isinstance(node, str):
        result.example_texts.append(node)
    elif isinstance(node, dict):
        for value in node.values():
            _collect_example_values(value, result)
    elif isinstance(node, list):
        for item in node:
            _collect_example_values(item, result)
    # non-string scalars (numbers/booleans/None) carry no maskable text


def _walk_xml(node: Any, result: ParsedDocument) -> None:
    tag = etree.QName(node).localname
    if tag == "documentation":
        if node.text:
            result.prose_texts.append(node.text)
    else:
        result.structural_texts.append(tag)
        for attr_name, attr_value in node.attrib.items():
            local_attr = attr_name.split("}")[-1]
            result.structural_texts.append(local_attr)
            if local_attr in ("name", "type", "base", "ref", "substitutionGroup"):
                result.structural_texts.append(attr_value)
    for child in node:
        _walk_xml(child, result)
