"""
XSD parser (Section 4.4; Section 2.3 tech-stack row: "Parsing - XSD/WSDL |
lxml with a custom type flattener | Substitution groups and xsd:choice
preserved, see Section 4.4"). Five idioms, each independently applied:

- xs:choice: "MUST be preserved as business polymorphism. Emits one
  AttributeRecord per branch with a shared typeDetail.choiceGroup
  identifier and obligation.level = conditional. MUST NOT be flattened
  into a set of independent optional fields."
- Substitution groups: "Head element emits a record with
  typeDetail.substitutionHead = true; each member emits a record
  referencing the head." (the field name for "referencing the head" -
  typeDetail.substitutionOf, holding the head's attributeId - is not
  named in the spec; a builder decision, by analogy with refTarget.)
- Attribute versus element: "Normalised away... Failing to do this
  double-counts the concept and corrupts the denominator." Enforced here
  by _walk_attribute and the element branch of _walk_container sharing
  the exact same downstream record-building call.
- nillable and minOccurs: "different things and MUST NOT be conflated" -
  read independently off separate XML attributes.
- xs:extension hierarchies: "Flattened with inherited members marked
  typeDetail.inheritedFrom."

Every top-level xs:element in the schema is walked as its own root
concept (not just one designated "document root") - this is what lets a
substitution-group head and member, both declared as independent
top-level elements, each get their own self-record.

parse_wsdl (parsers/wsdl.py) shares _parse_xsd_tree with this module.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from lxml import etree

from generated.C1.SourceArtefact._1_0 import C1Sourceartefact
from generated.C5.AttributeRecord._1_0 import C5Attributerecord
from generated.common.defs import DataType

from parsers.record_builder import build_record
from parsers.type_normalisation import from_xsd_qname

_XS_NS = "http://www.w3.org/2001/XMLSchema"


def _qname(node: Any) -> str:
    return str(etree.QName(node).localname)


def _strip_prefix(qname: str | None) -> str | None:
    if qname is None:
        return None
    return qname.split(":", 1)[-1]


def _locator_for(node: Any) -> str:
    try:
        return str(node.getroottree().getpath(node))
    except Exception:
        return f"#{id(node)}"


def _cardinality_for(is_required: bool, is_array: bool) -> str:
    if is_array:
        return "1..n" if is_required else "0..n"
    return "1..1" if is_required else "0..1"


def parse_xsd(content: bytes, source_artefact: C1Sourceartefact, run_id: UUID) -> list[C5Attributerecord]:
    root = etree.fromstring(content)
    return _parse_xsd_tree(root, source_artefact, run_id)


def _parse_xsd_tree(schema_node: Any, source_artefact: C1Sourceartefact, run_id: UUID) -> list[C5Attributerecord]:
    complex_types = {
        ct.get("name"): ct
        for ct in schema_node.findall(f"{{{_XS_NS}}}complexType")
        if ct.get("name")
    }
    top_level_elements = {
        el.get("name"): el
        for el in schema_node.findall(f"{{{_XS_NS}}}element")
        if el.get("name")
    }

    records: list[C5Attributerecord] = []

    for name, element_node in top_level_elements.items():
        substitution_group = _strip_prefix(element_node.get("substitutionGroup"))
        records.extend(_walk_element(
            element_node,
            path=name,
            is_substitution_head=any(
                _strip_prefix(other.get("substitutionGroup")) == name
                for other in top_level_elements.values()
            ),
            # attributeId is deterministic (attr://{region}/{artefactId}/{path}),
            # so the head's id can be computed directly here without needing
            # to walk the head first - no fragile two-pass fixup required.
            substitution_of=(
                f"attr://{source_artefact.region.value}/{source_artefact.artefactId}/{substitution_group}"
                if substitution_group else None
            ),
            complex_types=complex_types,
            source_artefact=source_artefact,
            run_id=run_id,
        ))

    return records


def _walk_element(
    element_node: Any,
    *,
    path: str,
    complex_types: dict[str, Any],
    source_artefact: C1Sourceartefact,
    run_id: UUID,
    parent_path: str | None = None,
    choice_group: str | None = None,
    inherited_from: str | None = None,
    is_substitution_head: bool = False,
    substitution_of: str | None = None,
) -> list[C5Attributerecord]:
    local_name = path.rsplit(".", 1)[-1]
    nillable = element_node.get("nillable") == "true"
    min_occurs = element_node.get("minOccurs", "1")
    max_occurs = element_node.get("maxOccurs", "1")
    is_required = min_occurs != "0"
    is_array = max_occurs not in ("0", "1")

    type_attr = _strip_prefix(element_node.get("type"))
    inline_complex = element_node.find(f"{{{_XS_NS}}}complexType")
    named_complex = complex_types.get(type_attr) if type_attr else None

    obligation_level = "conditional" if choice_group else ("mandatory" if is_required else "optional")
    documentation = _documentation_of(element_node)

    type_detail: dict[str, Any] = {}
    if choice_group:
        type_detail["choiceGroup"] = choice_group
    if is_substitution_head:
        type_detail["substitutionHead"] = True
    if substitution_of:
        type_detail["substitutionOf"] = substitution_of
    if nillable:
        type_detail["explicitNull"] = True
    if inherited_from:
        type_detail["inheritedFrom"] = inherited_from

    records: list[C5Attributerecord] = []

    complex_node = inline_complex if inline_complex is not None else named_complex
    if complex_node is not None:
        records.append(build_record(
            source_artefact=source_artefact, run_id=run_id, path=path, local_name=local_name,
            parent_path=parent_path, data_type=DataType.object, type_detail=type_detail,
            cardinality=_cardinality_for(is_required, is_array), obligation_level=obligation_level,
            locator=_locator_for(element_node), description=documentation,
        ))
        records.extend(_walk_complex_type(
            complex_node, path=path, complex_types=complex_types,
            source_artefact=source_artefact, run_id=run_id,
        ))
        return records

    normalised = from_xsd_qname(f"xs:{type_attr}") if type_attr else from_xsd_qname("")
    merged_detail = {**normalised.type_detail, **type_detail}
    records.append(build_record(
        source_artefact=source_artefact, run_id=run_id, path=path, local_name=local_name,
        parent_path=parent_path, data_type=normalised.data_type, type_detail=merged_detail,
        cardinality=_cardinality_for(is_required, is_array), obligation_level=obligation_level,
        locator=_locator_for(element_node), description=documentation,
    ))
    return records


def _walk_attribute(
    attribute_node: Any,
    *,
    path: str,
    parent_path: str,
    source_artefact: C1Sourceartefact,
    run_id: UUID,
    inherited_from: str | None = None,
) -> list[C5Attributerecord]:
    name = attribute_node.get("name")
    full_path = f"{path}.{name}"
    type_attr = _strip_prefix(attribute_node.get("type"))
    normalised = from_xsd_qname(f"xs:{type_attr}") if type_attr else from_xsd_qname("")
    type_detail = dict(normalised.type_detail)
    if inherited_from:
        type_detail["inheritedFrom"] = inherited_from

    use = attribute_node.get("use", "optional")
    is_required = use == "required"

    return [build_record(
        source_artefact=source_artefact, run_id=run_id, path=full_path, local_name=str(name),
        parent_path=path, data_type=normalised.data_type, type_detail=type_detail,
        cardinality=_cardinality_for(is_required, is_array=False),
        obligation_level="mandatory" if is_required else "optional",
        locator=_locator_for(attribute_node), description=_documentation_of(attribute_node),
    )]


def _walk_complex_type(
    complex_node: Any,
    *,
    path: str,
    complex_types: dict[str, Any],
    source_artefact: C1Sourceartefact,
    run_id: UUID,
) -> list[C5Attributerecord]:
    extension = complex_node.find(f"{{{_XS_NS}}}complexContent/{{{_XS_NS}}}extension")
    if extension is not None:
        records: list[C5Attributerecord] = []
        base_name = _strip_prefix(extension.get("base"))
        base_complex = complex_types.get(base_name) if base_name else None
        if base_complex is not None:
            records.extend(_walk_container(
                base_complex, path=path, complex_types=complex_types,
                source_artefact=source_artefact, run_id=run_id, inherited_from=base_name,
            ))
        records.extend(_walk_container(
            extension, path=path, complex_types=complex_types,
            source_artefact=source_artefact, run_id=run_id, inherited_from=None,
        ))
        return records

    return _walk_container(
        complex_node, path=path, complex_types=complex_types,
        source_artefact=source_artefact, run_id=run_id, inherited_from=None,
    )


def _walk_container(
    container_node: Any,
    *,
    path: str,
    complex_types: dict[str, Any],
    source_artefact: C1Sourceartefact,
    run_id: UUID,
    inherited_from: str | None,
) -> list[C5Attributerecord]:
    records: list[C5Attributerecord] = []
    for child in container_node:
        tag = _qname(child)
        if tag == "sequence" or tag == "all":
            records.extend(_walk_container(
                child, path=path, complex_types=complex_types,
                source_artefact=source_artefact, run_id=run_id, inherited_from=inherited_from,
            ))
        elif tag == "choice":
            group_id = child.get("id") or f"{path}.choice"
            for branch in child:
                if _qname(branch) != "element":
                    continue
                branch_name = branch.get("name")
                records.extend(_walk_element(
                    branch, path=f"{path}.{branch_name}", parent_path=path,
                    choice_group=group_id, complex_types=complex_types,
                    source_artefact=source_artefact, run_id=run_id,
                ))
        elif tag == "element":
            name = child.get("name")
            records.extend(_walk_element(
                child, path=f"{path}.{name}", parent_path=path,
                inherited_from=inherited_from, complex_types=complex_types,
                source_artefact=source_artefact, run_id=run_id,
            ))
        elif tag == "attribute":
            records.extend(_walk_attribute(
                child, path=path, parent_path=path,
                source_artefact=source_artefact, run_id=run_id, inherited_from=inherited_from,
            ))
    return records


def _documentation_of(node: Any) -> str | None:
    doc = node.find(f"{{{_XS_NS}}}annotation/{{{_XS_NS}}}documentation")
    if doc is None or doc.text is None:
        return None
    return doc.text.strip() or None
