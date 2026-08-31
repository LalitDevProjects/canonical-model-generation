from __future__ import annotations

from pathlib import Path

from connectors.base import ConnectorScope
from connectors.confluence_connector import ConfluenceConnector


class TestConfluenceConnectorDiscover:
    def test_discovers_the_fixture_page(self, golden_confluence_dir: Path) -> None:
        connector = ConfluenceConnector(golden_confluence_dir, region="uk")
        refs = list(connector.discover(ConnectorScope(region="uk", domain="claims")))
        assert len(refs) == 1
        ref = refs[0]
        assert ref.uri == "confluence://CLAIMSUK/123456"
        assert ref.system == "confluence"
        assert ref.region == "uk"
        assert ref.title == "Claims UK - FNOL Glossary"
        assert ref.media_type == "application/vnd.atlassian.confluence.storage+xml"

    def test_description_strips_html_tags(self, golden_confluence_dir: Path) -> None:
        connector = ConfluenceConnector(golden_confluence_dir, region="uk")
        ref = next(iter(connector.discover(ConnectorScope(region="uk", domain="claims"))))
        assert ref.description is not None
        assert "<" not in ref.description
        assert "FNOL" in ref.description


class TestConfluenceConnectorFetch:
    def test_fetch_returns_storage_format_content_and_page_version(self, golden_confluence_dir: Path) -> None:
        connector = ConfluenceConnector(golden_confluence_dir, region="uk")
        ref = next(iter(connector.discover(ConnectorScope(region="uk", domain="claims"))))
        raw = connector.fetch(ref)
        assert raw.version == "42"
        assert b"<h1>FNOL Glossary</h1>" in raw.content
        assert raw.media_type == ref.media_type


class TestConfluenceConnectorHealth:
    def test_ok_for_real_fixtures_dir(self, golden_confluence_dir: Path) -> None:
        connector = ConfluenceConnector(golden_confluence_dir, region="uk")
        status = connector.health()
        assert status.ok is True
        assert status.system == "confluence"

    def test_not_ok_for_missing_dir(self, tmp_path: Path) -> None:
        connector = ConfluenceConnector(tmp_path / "does-not-exist", region="uk")
        status = connector.health()
        assert status.ok is False
        assert "missing" in status.detail
