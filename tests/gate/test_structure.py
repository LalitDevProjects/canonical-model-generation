from __future__ import annotations

from gate.structure import parse_structure


class TestJsonLike:
    def test_keys_are_structural(self) -> None:
        content = b'{"claimId": {"type": "string", "description": "Unique id."}}'
        doc = parse_structure(content, "application/json")
        assert doc.kind == "json_like"
        assert "claimId" in doc.structural_texts
        assert "type" in doc.structural_texts

    def test_description_is_prose(self) -> None:
        content = b'{"claimId": {"type": "string", "description": "Unique id."}}'
        doc = parse_structure(content, "application/json")
        assert doc.prose_texts == ["Unique id."]

    def test_example_value_captured(self) -> None:
        content = b'{"claimant": {"type": "string", "example": "A. Smith, SW1A 1AA"}}'
        doc = parse_structure(content, "application/yaml")
        assert doc.example_texts == ["A. Smith, SW1A 1AA"]

    def test_nested_example_object_walked_recursively(self) -> None:
        content = b'{"party": {"example": {"name": "Jane Doe", "id": 42}}}'
        doc = parse_structure(content, "application/yaml")
        assert "Jane Doe" in doc.example_texts

    def test_malformed_yaml_falls_back_to_whole_body_prose(self) -> None:
        content = b"{ this is not: valid: yaml: at all: ]["
        doc = parse_structure(content, "application/yaml")
        assert doc.kind == "none"
        assert len(doc.prose_texts) == 1


class TestXml:
    def test_element_and_attribute_names_are_structural(self) -> None:
        content = b"""<?xml version="1.0"?>
<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">
  <xs:element name="claimId" type="xs:string"/>
</xs:schema>"""
        doc = parse_structure(content, "application/xml")
        assert doc.kind == "xml"
        assert "element" in doc.structural_texts
        assert "name" in doc.structural_texts
        assert "claimId" in doc.structural_texts

    def test_documentation_text_is_prose(self) -> None:
        content = b"""<?xml version="1.0"?>
<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">
  <xs:element name="notificationDate" type="xs:string">
    <xs:annotation><xs:documentation>Date the notification was received.</xs:documentation></xs:annotation>
  </xs:element>
</xs:schema>"""
        doc = parse_structure(content, "application/xml")
        assert "Date the notification was received." in doc.prose_texts

    def test_malformed_xml_falls_back_to_whole_body_prose(self) -> None:
        content = b"<not><valid"
        doc = parse_structure(content, "application/xml")
        assert doc.kind == "none"


class TestAvro:
    def test_field_names_are_structural(self) -> None:
        content = b'{"type": "record", "name": "ClaimEvent", "fields": [{"name": "claimId", "type": "string"}]}'
        doc = parse_structure(content, "application/vnd.apache.avro+json")
        assert doc.kind == "avro"
        assert "claimId" in doc.structural_texts


class TestNoStructuralParser:
    def test_confluence_media_type_treated_as_whole_body_prose(self) -> None:
        content = b"<h1>FNOL Glossary</h1><p>First Notification of Loss.</p>"
        doc = parse_structure(content, "application/vnd.atlassian.confluence.storage+xml")
        assert doc.kind == "none"
        assert doc.prose_texts == [content.decode("utf-8")]

    def test_unrecognised_media_type_treated_as_whole_body_prose(self) -> None:
        content = b"some opaque binary-ish content"
        doc = parse_structure(content, "application/octet-stream")
        assert doc.kind == "none"
        assert doc.prose_texts == [content.decode("utf-8")]
