from __future__ import annotations

from uuid import uuid4

import pytest
from golden_helpers import golden_avro, golden_git, golden_wsdl, golden_xsd, make_source_artefact

from parsers import router

RUN_ID = uuid4()


class TestRouterDispatch:
    def test_dispatches_openapi(self) -> None:
        content = golden_git("claims-us/openapi.yaml")
        source_artefact = make_source_artefact("application/yaml")
        records = router.parse(content, source_artefact, RUN_ID)
        assert any(r.path == "Claim.claimId" for r in records)

    def test_dispatches_xml_to_xsd_by_default(self) -> None:
        content = golden_xsd("uk/ClaimNotification.xsd")
        source_artefact = make_source_artefact("application/xml")
        records = router.parse(content, source_artefact, RUN_ID)
        assert any(r.path == "ClaimNotification.notificationDate" for r in records)

    def test_dispatches_xml_to_wsdl_when_root_is_definitions(self) -> None:
        content = golden_wsdl("uk/ClaimNotificationService.wsdl")
        source_artefact = make_source_artefact("application/xml")
        records = router.parse(content, source_artefact, RUN_ID)
        assert any(r.path == "ClaimNotification.notificationDate" for r in records)

    def test_dispatches_avro(self) -> None:
        content = golden_avro("us/ClaimEvent.avsc")
        source_artefact = make_source_artefact("application/vnd.apache.avro+json")
        records = router.parse(content, source_artefact, RUN_ID)
        assert any(r.path == "ClaimEvent.claimId" for r in records)

    def test_unregistered_media_type_raises(self) -> None:
        source_artefact = make_source_artefact("application/octet-stream")
        with pytest.raises(ValueError, match="no parser registered"):
            router.parse(b"whatever", source_artefact, RUN_ID)

    def test_missing_media_type_raises(self) -> None:
        source_artefact = make_source_artefact("application/yaml").model_copy(update={"mediaType": None})
        with pytest.raises(ValueError, match="no parser registered"):
            router.parse(b"whatever", source_artefact, RUN_ID)
