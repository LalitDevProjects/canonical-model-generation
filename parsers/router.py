"""
Dispatches a fetched artefact's raw content to the right parser by
mediaType. .xsd and .wsdl currently share media_type="application/xml"
(connectors/git_connector.py's extension table), so they're disambiguated
by root element tag rather than by mediaType alone - mediaType is what the
router is actually told, but a WSDL document's own root element
(wsdl:definitions) is unambiguous and cheap to check.
"""

from __future__ import annotations

from collections.abc import Callable
from uuid import UUID

from lxml import etree

from generated.C1.SourceArtefact._1_0 import C1Sourceartefact
from generated.C5.AttributeRecord._1_0 import C5Attributerecord

from parsers.avro import parse_avro
from parsers.openapi import parse_openapi
from parsers.wsdl import parse_wsdl
from parsers.xsd import parse_xsd

_WSDL_ROOT_TAG = "{http://schemas.xmlsoap.org/wsdl/}definitions"

ParserFn = Callable[[bytes, C1Sourceartefact, UUID], list[C5Attributerecord]]


def _dispatch_xml(content: bytes, source_artefact: C1Sourceartefact, run_id: UUID) -> list[C5Attributerecord]:
    root_tag = etree.fromstring(content).tag
    if root_tag == _WSDL_ROOT_TAG:
        return parse_wsdl(content, source_artefact, run_id)
    return parse_xsd(content, source_artefact, run_id)


_PARSERS: dict[str, ParserFn] = {
    "application/vnd.oai.openapi": parse_openapi,
    "application/yaml": parse_openapi,
    "application/x-yaml": parse_openapi,
    "application/json": parse_openapi,
    "application/schema+json": parse_openapi,
    "application/xml": _dispatch_xml,
    "application/vnd.apache.avro+json": parse_avro,
}


def parse(content: bytes, source_artefact: C1Sourceartefact, run_id: UUID) -> list[C5Attributerecord]:
    media_type = source_artefact.mediaType
    parser = _PARSERS.get(media_type) if media_type else None
    if parser is None:
        raise ValueError(f"no parser registered for mediaType={media_type!r} (artefact {source_artefact.artefactId!r})")
    return parser(content, source_artefact, run_id)
