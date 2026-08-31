from __future__ import annotations

import json
from pathlib import Path

from substrate.chunking import (
    ChunkDraft,
    chunk,
    chunk_avro,
    chunk_confluence,
    chunk_openapi,
    chunk_wsdl,
    chunk_xsd,
    compute_chunk_hash,
)

from helpers import make_artefact

REPO_ROOT = Path(__file__).resolve().parents[2]
GOLDEN_OPENAPI = REPO_ROOT / "golden" / "git" / "claims-uk" / "openapi.yaml"
GOLDEN_XSD = REPO_ROOT / "golden" / "xsd" / "uk" / "ClaimNotification.xsd"
GOLDEN_WSDL = REPO_ROOT / "golden" / "wsdl" / "uk" / "ClaimNotificationService.wsdl"
GOLDEN_AVRO = REPO_ROOT / "golden" / "avro" / "us" / "ClaimEvent.avsc"
GOLDEN_CONFLUENCE = REPO_ROOT / "golden" / "confluence" / "claims-uk-glossary.json"


class TestComputeChunkHash:
    def test_deterministic(self) -> None:
        assert compute_chunk_hash("hello world") == compute_chunk_hash("hello world")

    def test_whitespace_insensitive(self) -> None:
        assert compute_chunk_hash("hello   world") == compute_chunk_hash("hello world")

    def test_different_text_different_hash(self) -> None:
        assert compute_chunk_hash("hello") != compute_chunk_hash("world")

    def test_is_a_64_char_hex_digest(self) -> None:
        digest = compute_chunk_hash("x")
        assert len(digest) == 64
        assert all(c in "0123456789abcdef" for c in digest)


class TestChunkOpenapi:
    def test_one_chunk_per_named_schema_component(self) -> None:
        content = GOLDEN_OPENAPI.read_bytes()
        artefact = make_artefact(content=content, media_type="application/yaml")
        chunks = chunk_openapi(content, artefact)
        assert [c.artefact_kind for c in chunks] == ["openapi"]
        assert "Claim" in chunks[0].text

    def test_chunk_carries_the_expected_metadata(self) -> None:
        content = GOLDEN_OPENAPI.read_bytes()
        artefact = make_artefact(artefact_id="art-openapi", region="uk", content=content, media_type="application/yaml", evidence_tier=1)
        [claim_chunk] = chunk_openapi(content, artefact)
        assert claim_chunk.artefact_id == "art-openapi"
        assert claim_chunk.region == "uk"
        assert claim_chunk.evidence_tier == 1
        assert claim_chunk.content_hash == artefact.contentHash
        assert claim_chunk.evref.startswith("evref://uk/git/art-openapi@")
        assert claim_chunk.evref.endswith("#components/schemas/Claim")
        assert claim_chunk.chunk_hash == compute_chunk_hash(claim_chunk.text)

    def test_ref_closure_inlined_to_depth_one_not_further(self) -> None:
        content = b"""
        components:
          schemas:
            Claim:
              type: object
              properties:
                claimant:
                  $ref: '#/components/schemas/Party'
            Party:
              type: object
              properties:
                address:
                  $ref: '#/components/schemas/Address'
            Address:
              type: object
              properties:
                postcode:
                  type: string
        """
        artefact = make_artefact(content=content, media_type="application/yaml")
        chunks = {c.text.splitlines()[0]: c.text for c in chunk_openapi(content, artefact)}
        # Claim's chunk inlines Party's own body (depth 1)...
        assert "Party" in chunks["Claim"]
        assert "address" in chunks["Claim"]
        # ...but does NOT further resolve Party's own $ref to Address.
        assert "postcode" not in chunks["Claim"]
        # Party's own chunk, taken independently, does inline Address.
        assert "postcode" in chunks["Party"]


class TestChunkXsd:
    def test_one_chunk_per_complex_type_or_inline_typed_element(self) -> None:
        content = GOLDEN_XSD.read_bytes()
        artefact = make_artefact(content=content, media_type="application/xml")
        chunks = chunk_xsd(content, artefact)
        names = [c.text.splitlines()[0] for c in chunks]
        assert names == [
            "BaseNotificationEventType",
            "UrgentNotificationEventType",
            "ClaimNotification",
            "BrokerNotifierType",
            "PolicyholderNotifierType",
            "ThirdPartyNotifierType",
        ]

    def test_inherited_members_are_inlined(self) -> None:
        content = GOLDEN_XSD.read_bytes()
        artefact = make_artefact(content=content, media_type="application/xml")
        [urgent_chunk] = [c for c in chunk_xsd(content, artefact) if c.text.startswith("UrgentNotificationEventType")]
        # eventId is inherited from BaseNotificationEventType via
        # complexContent/extension - it must appear even though this
        # type's own <xs:extension> body never mentions it directly.
        assert "eventId" in urgent_chunk.text
        assert "receivedAt" in urgent_chunk.text
        assert "escalationReason" in urgent_chunk.text

    def test_choice_group_and_attribute_are_captured(self) -> None:
        content = GOLDEN_XSD.read_bytes()
        artefact = make_artefact(content=content, media_type="application/xml")
        [notification_chunk] = [c for c in chunk_xsd(content, artefact) if c.text.startswith("ClaimNotification")]
        assert "choice(notifier)" in notification_chunk.text
        assert "brokerNotifier" in notification_chunk.text
        assert "@claimReference" in notification_chunk.text

    def test_via_dispatch_produces_the_same_result(self) -> None:
        content = GOLDEN_XSD.read_bytes()
        artefact = make_artefact(content=content, media_type="application/xml")
        assert chunk(content, artefact) == chunk_xsd(content, artefact)

    def test_untyped_element_falls_back_to_a_placeholder_type_name(self) -> None:
        content = b"""<?xml version="1.0"?>
        <xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">
          <xs:element name="Loose">
            <xs:complexType>
              <xs:sequence>
                <xs:element name="untypedField"/>
              </xs:sequence>
            </xs:complexType>
          </xs:element>
        </xs:schema>"""
        artefact = make_artefact(content=content, media_type="application/xml")
        [loose_chunk] = chunk_xsd(content, artefact)
        assert "untypedField: ?" in loose_chunk.text


class TestChunkWsdl:
    def test_one_chunk_per_operation_not_per_embedded_type(self) -> None:
        content = GOLDEN_WSDL.read_bytes()
        artefact = make_artefact(content=content, media_type="application/xml")
        chunks = chunk_wsdl(content, artefact)
        assert len(chunks) == 1
        assert chunks[0].text.startswith("SubmitClaimNotification")
        assert "ClaimNotification" in chunks[0].text

    def test_via_dispatch_produces_the_same_result(self) -> None:
        content = GOLDEN_WSDL.read_bytes()
        artefact = make_artefact(content=content, media_type="application/xml")
        assert chunk(content, artefact) == chunk_wsdl(content, artefact)

    def test_operation_with_no_name_is_skipped(self) -> None:
        content = b"""<?xml version="1.0"?>
        <wsdl:definitions xmlns:wsdl="http://schemas.xmlsoap.org/wsdl/">
          <wsdl:portType name="X">
            <wsdl:operation>
              <wsdl:input message="tns:Whatever"/>
            </wsdl:operation>
          </wsdl:portType>
        </wsdl:definitions>"""
        artefact = make_artefact(content=content, media_type="application/xml")
        assert chunk_wsdl(content, artefact) == []


class TestChunkConfluence:
    def test_single_heading_document_is_one_chunk(self) -> None:
        page = json.loads(GOLDEN_CONFLUENCE.read_bytes())
        content = page["body"]["storage"]["value"].encode("utf-8")
        artefact = make_artefact(content=content, media_type="application/vnd.atlassian.confluence.storage+xml", system="confluence")
        chunks = chunk_confluence(content, artefact)
        assert len(chunks) == 1
        assert chunks[0].text.startswith("FNOL Glossary")
        assert "First Notification of Loss" in chunks[0].text

    def test_multiple_headings_produce_separate_chunks(self) -> None:
        content = b"<h1>Alpha</h1><p>alpha body text.</p><h2>Beta</h2><p>beta body text.</p>"
        artefact = make_artefact(content=content, media_type="application/vnd.atlassian.confluence.storage+xml", system="confluence")
        chunks = chunk_confluence(content, artefact)
        assert [c.text.splitlines()[0] for c in chunks] == ["Alpha", "Beta"]

    def test_long_body_is_split_with_overlap(self) -> None:
        words = " ".join(f"word{i}" for i in range(2000))
        content = f"<h1>Long</h1><p>{words}</p>".encode("utf-8")
        artefact = make_artefact(content=content, media_type="application/vnd.atlassian.confluence.storage+xml", system="confluence")
        chunks = chunk_confluence(content, artefact)
        assert len(chunks) > 1
        # 15% overlap: the tail of one piece reappears at the head of the next.
        first_words = chunks[0].text.split()
        second_words = chunks[1].text.split()
        assert first_words[-1] in second_words[:len(second_words) // 2 + 1]

    def test_no_headings_falls_back_to_a_single_whole_body_chunk(self) -> None:
        content = b"<p>No headings here, just a short paragraph.</p>"
        artefact = make_artefact(content=content, media_type="application/vnd.atlassian.confluence.storage+xml", system="confluence")
        chunks = chunk_confluence(content, artefact)
        assert len(chunks) == 1
        assert "No headings here" in chunks[0].text


class TestChunkAvro:
    def test_one_chunk_per_named_record(self) -> None:
        content = GOLDEN_AVRO.read_bytes()
        artefact = make_artefact(content=content, media_type="application/vnd.apache.avro+json", system="git", region="us")
        chunks = chunk_avro(content, artefact)
        assert len(chunks) == 1
        assert chunks[0].text.startswith("ClaimEvent")
        assert "reserveAmount" in chunks[0].text

    def test_nested_named_types_get_their_own_chunk(self) -> None:
        content = json.dumps({
            "type": "record", "name": "Outer",
            "fields": [
                {"name": "status", "type": {"type": "enum", "name": "Status", "symbols": ["OPEN", "CLOSED"]}},
            ],
        }).encode("utf-8")
        artefact = make_artefact(content=content, media_type="application/vnd.apache.avro+json", system="git", region="us")
        chunks = chunk_avro(content, artefact)
        names = {c.text.splitlines()[0] for c in chunks}
        assert names == {"Outer", "Status"}


class TestChunkDispatch:
    def test_no_registered_chunker_returns_empty_list_not_an_error(self) -> None:
        artefact = make_artefact(content=b"whatever", media_type="application/octet-stream")
        assert chunk(b"whatever", artefact) == []

    def test_none_media_type_returns_empty_list(self) -> None:
        content = b"whatever"
        artefact = make_artefact(content=content, media_type="application/yaml")
        artefact = artefact.model_copy(update={"mediaType": None})
        assert chunk(content, artefact) == []

    def test_every_draft_is_a_chunk_draft(self) -> None:
        content = GOLDEN_OPENAPI.read_bytes()
        artefact = make_artefact(content=content, media_type="application/yaml")
        for draft in chunk(content, artefact):
            assert isinstance(draft, ChunkDraft)
