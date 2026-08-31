"""
WSDL parser (Section 4.4). Confirmed by direct spec search: WSDL is
treated ONLY as an XSD-type carrier - "The SOAP tail carries some of the
oldest and most business-critical claims interfaces" motivates first-class
treatment, but nothing in the spec asks for WSDL-specific extraction
(operations/ports/bindings/messages). This module extracts the embedded
<xsd:schema> under wsdl:types and delegates entirely to parsers.xsd's
shared _parse_xsd_tree - "XSD plus an operation wrapper we ignore for
attribute extraction purposes."
"""

from __future__ import annotations

from uuid import UUID

from lxml import etree

from generated.C1.SourceArtefact._1_0 import C1Sourceartefact
from generated.C5.AttributeRecord._1_0 import C5Attributerecord

from parsers.xsd import _XS_NS, _parse_xsd_tree

_WSDL_NS = "http://schemas.xmlsoap.org/wsdl/"


def parse_wsdl(content: bytes, source_artefact: C1Sourceartefact, run_id: UUID) -> list[C5Attributerecord]:
    root = etree.fromstring(content)
    records: list[C5Attributerecord] = []
    types = root.find(f"{{{_WSDL_NS}}}types")
    if types is None:
        return records
    for schema_node in types.findall(f"{{{_XS_NS}}}schema"):
        records.extend(_parse_xsd_tree(schema_node, source_artefact, run_id))
    return records
