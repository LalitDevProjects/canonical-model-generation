"""
One light integration test proving a real Increment-2 GitConnector feeds a
real Increment-3 parser end-to-end, via router.parse's mediaType dispatch.
No new golden fixtures - reuses the existing golden/git/claims-us/ corpus
from Increment 2 unchanged.
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from golden_helpers import build_golden_git_repo

from generated.C1.SourceArtefact._1_0 import C1Sourceartefact

from connectors.base import ConnectorScope
from connectors.git_connector import GitConnector
from parsers import router


def test_git_connector_fetch_feeds_router_to_openapi_parser(tmp_path: Path) -> None:
    repo_path = build_golden_git_repo(tmp_path)
    connector = GitConnector(repo_path, region="us")

    refs = {
        ref.metadata["path"]: ref
        for ref in connector.discover(ConnectorScope(region="us", domain="claims"))
    }
    ref = refs["claims-us/openapi.yaml"]
    raw = connector.fetch(ref)

    source_artefact = C1Sourceartefact.model_validate({
        "artefactId": "git-us-claims-us-openapi",
        "region": "us",
        "system": "git",
        "uri": ref.uri,
        "version": raw.version,
        "contentHash": "b" * 64,
        "mediaType": raw.media_type,
        "evidenceTier": 1,
        "sanitisation": {
            "artefactId": "git-us-claims-us-openapi",
            "contentHash": "b" * 64,
            "labels": ["STRUCTURAL"],
            "verdict": "allow",
            "licenceDisposition": "permitted",
            "policyVersion": 1,
            "classifiedAt": "2026-08-20T09:00:00Z",
        },
    })

    records = router.parse(raw.content, source_artefact, uuid4())

    reserve_amount = next(r for r in records if r.path == "Claim.reserveAmount")
    assert reserve_amount.dataType == "decimal"
    loss_date = next(r for r in records if r.path == "Claim.lossDate")
    assert loss_date.dataType == "string"
