"""
Confluence connector (Section 4.1). Pinning strategy: "Page version number.
Retrieves storage-format XHTML, not rendered HTML, so that macros and
structure survive."

No real Confluence instance exists or is planned for this platform yet.
This connector reads local JSON fixtures shaped like a plausible Confluence
Cloud REST API response (GET /content/{id}?expand=body.storage,version,space)
under a fixtures directory (golden/confluence/ for the golden corpus) - an
honest, clearly-documented stand-in, not a real integration.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from connectors.base import ArtefactRef, Connector, ConnectorScope, HealthStatus, RawArtefact

_TAG_RE = re.compile(r"<[^>]+>")


def _strip_tags(html: str) -> str:
    """Good enough for a short description preview; not a real HTML
    parser (that's I3/I4 territory if it ever needs to be more)."""
    return _TAG_RE.sub("", html)


def _load_page(path: Path) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return data


class ConfluenceConnector(Connector):
    system = "confluence"

    def __init__(self, fixtures_dir: Path, region: str) -> None:
        self._fixtures_dir = fixtures_dir
        self._region = region

    def discover(self, scope: ConnectorScope) -> Iterator[ArtefactRef]:
        for path in sorted(self._fixtures_dir.glob("*.json")):
            page = _load_page(path)
            description = _strip_tags(page["body"]["storage"]["value"])[:280]
            yield ArtefactRef(
                uri=f"confluence://{page['space']['key']}/{page['id']}",
                system=self.system,
                region=self._region,
                media_type="application/vnd.atlassian.confluence.storage+xml",
                title=page["title"],
                description=description,
                metadata={"fixture_path": str(path)},
            )

    def fetch(self, ref: ArtefactRef) -> RawArtefact:
        page = _load_page(Path(ref.metadata["fixture_path"]))
        content = page["body"]["storage"]["value"].encode("utf-8")
        return RawArtefact(
            uri=ref.uri,
            version=str(page["version"]["number"]),
            content=content,
            media_type=ref.media_type,
            owning_team=None,
            metadata={"title": page["title"]},
        )

    def health(self) -> HealthStatus:
        if not self._fixtures_dir.is_dir():
            return HealthStatus(system=self.system, ok=False, detail=f"{self._fixtures_dir} missing")
        return HealthStatus(system=self.system, ok=True)
