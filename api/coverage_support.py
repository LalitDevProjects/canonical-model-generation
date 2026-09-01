"""
Shared coverage-universe assembly for api/run_control.py's GET .../coverage
and .../gaps, and api/registry.py's POST .../releases gate check - the
same live computation, reused rather than duplicated.
"""

from __future__ import annotations

from uuid import UUID

from generated.C8.CanonicalCandidate._1_0 import C8Canonicalcandidate

from algorithms.coverage import Concept, build_universe
from config.settings import PlatformSettings
from contracts.validators import unwrap_ref
from pipeline.run_store import RunStore
from substrate.api import SubstrateApi
from substrate.db import SubstrateDb


def hermetic_substrate(run_store: RunStore, settings: PlatformSettings) -> SubstrateApi:
    """Only get_attribute() is ever exercised by build_universe() here -
    the injected SubstrateDb's .connection() is never called, the same
    real, verified constraint pipeline/orchestrator.py's own
    _build_run_context() documents."""
    return SubstrateApi(
        db=SubstrateDb(dsn="postgresql://unused/unused"),
        run_store=run_store,
        dimensions=settings.models.embedding_dimensions,
        acord_ingestion_enabled=False,
    )


def live_universe(run_store: RunStore, run_id: UUID, settings: PlatformSettings) -> list[Concept] | None:
    """None if the run hasn't reached clustering yet (no clusters
    persisted) - the caller turns that into a 404."""
    clusters = run_store.read_clusters(run_id)
    if not clusters:
        return None
    candidates_by_cluster: dict[str, C8Canonicalcandidate] = {
        str(unwrap_ref(ref)): candidate
        for candidate in run_store.read_candidates(run_id)
        for ref in candidate.clusterRefs
    }
    substrate = hermetic_substrate(run_store, settings)
    return build_universe(clusters, candidates_by_cluster, substrate=substrate, run_id=str(run_id))
