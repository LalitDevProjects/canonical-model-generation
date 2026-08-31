from __future__ import annotations

from uuid import uuid4

from golden_helpers import golden_wsdl, make_source_artefact

from parsers.wsdl import parse_wsdl

RUN_ID = uuid4()


class TestParseWsdlDelegatesToXsd:
    """Proves delegation: the WSDL fixture wraps the exact same schema
    content as golden/xsd/uk/ClaimNotification.xsd, so parsing it should
    produce the same choice-branch shape the XSD parser itself proves."""

    def test_choice_group_survives_through_wsdl(self) -> None:
        content = golden_wsdl("uk/ClaimNotificationService.wsdl")
        source_artefact = make_source_artefact("application/xml", region="uk")
        records = parse_wsdl(content, source_artefact, RUN_ID)

        branches = [r for r in records if r.typeDetail and r.typeDetail.choiceGroup == "notifier"]
        assert len(branches) == 3
        assert all(r.obligation.level == "conditional" for r in branches)

    def test_untyped_date_survives_through_wsdl(self) -> None:
        content = golden_wsdl("uk/ClaimNotificationService.wsdl")
        source_artefact = make_source_artefact("application/xml", region="uk")
        records = parse_wsdl(content, source_artefact, RUN_ID)

        rec = next(r for r in records if r.path == "ClaimNotification.notificationDate")
        assert rec.dataType == "string"

    def test_no_types_element_yields_no_records(self) -> None:
        content = b"""<?xml version="1.0"?>
<wsdl:definitions xmlns:wsdl="http://schemas.xmlsoap.org/wsdl/"></wsdl:definitions>"""
        source_artefact = make_source_artefact("application/xml", region="uk")
        records = parse_wsdl(content, source_artefact, RUN_ID)
        assert records == []
