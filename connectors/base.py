"""
Connector interface (Section 4.1).

"All connectors implement one interface. Adding a source system MUST NOT
require changes anywhere else in the platform." discover() and fetch() are
deliberately separate methods - "so that relevance filtering happens before
download, not after" - so a large estate can be enumerated cheaply before
anything expensive (a real network fetch) runs on material that relevance
filtering will just throw away.

ArtefactRef, ConnectorScope and HealthStatus are referenced in the spec's
pseudocode but never defined there; their shapes here are sized to exactly
what connectors/relevance.py's scoring signals and connectors/manifest.py's
assembly need - not a general-purpose design, an Increment 2 builder
decision.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass, field


@dataclass(frozen=True)
class ArtefactRef:
    """A cheap, pre-download handle produced by discover(). Enough to
    pass-1 score (see connectors/relevance.py) and to fetch() later without
    re-enumerating."""

    uri: str
    system: str
    region: str
    media_type: str
    catalogue_domain: str | None = None
    """Only meaningful for a future `catalogue` connector (not built at
    Increment 2); always None from GitConnector/ConfluenceConnector, which
    have no concept of a service catalogue's declared domain."""
    has_live_route: bool = False
    """Only meaningful for a future gateway-aware connector; always False
    here since neither git nor Confluence content has an associated live
    route."""
    title: str | None = None
    description: str | None = None
    metadata: dict[str, str] = field(default_factory=dict)
    """Connector-private bookkeeping needed to fetch() this ref later, e.g.
    a git connector stores the pinned commit SHA and repo-relative path
    here rather than re-deriving them."""


@dataclass(frozen=True)
class RawArtefact:
    """The result of fetch(): content at a pinned version. content_hash is
    deliberately NOT computed here - connectors/manifest.py computes it
    once, centrally, so hashing policy lives in exactly one place."""

    uri: str
    version: str
    content: bytes
    media_type: str
    owning_team: str | None
    metadata: dict[str, str]


@dataclass(frozen=True)
class ConnectorScope:
    """What subset of one connector's estate to enumerate. Increment 2's
    connectors are each bound to one repo / one fixtures directory at
    construction time, so region/domain are informational rather than used
    to select among many repositories - a connector fronting a whole
    fleet would use them for that. Not schema-backed; a pure builder
    decision, not derived from spec text."""

    region: str
    domain: str
    include: tuple[str, ...] = ()
    exclude: tuple[str, ...] = ()


@dataclass(frozen=True)
class HealthStatus:
    """Credential validity and rate-limit headroom, checked before a run
    starts (spec's own docstring for Connector.health)."""

    system: str
    ok: bool
    detail: str = ""


class Connector(ABC):
    """One connector per source system (git, confluence, ...). system MUST
    match one of common.defs.System's enum values."""

    system: str

    @abstractmethod
    def discover(self, scope: ConnectorScope) -> Iterator[ArtefactRef]:
        """Enumerate candidate artefacts without downloading them. MUST be
        cheap: this runs over the whole estate before relevance filtering."""
        raise NotImplementedError

    @abstractmethod
    def fetch(self, ref: ArtefactRef) -> RawArtefact:
        """Retrieve one artefact at a PINNED version. MUST NOT resolve a
        moving reference such as a branch head."""
        raise NotImplementedError

    @abstractmethod
    def health(self) -> HealthStatus:
        """Credential validity and rate-limit headroom, checked before a
        run starts."""
        raise NotImplementedError
