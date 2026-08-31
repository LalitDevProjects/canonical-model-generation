"""
The workshop pack (Section 17.4: "emit/ # schema, openapi, logical model,
workshop pack emitters"; S8's own exit criterion: "Schemas validate;
mappings pass round-trip tests; workshop pack complete"). A real
directory of files an SME can open in a workshop session, plus one
indexing manifest (sha256 + description per file) so the pack's own
completeness and integrity can be checked without opening every document.

"Complete enough to run a real session from" is grounded in what this
repo can actually produce for real from Increments 1-9's own outputs:
validating entity/extension/common schemas, an OpenAPI projection, at
least one compiled mapping spec with a real round-trip result, the real
coverage report and gap register (Increment 8), a logical model with real
lineage strings, and a release manifest. What is honestly NOT real in
this repo - ACORD alignment content, since ACORD Reference Architecture
data has been unavailable since Increment 1 - is written as a real,
labelled manual-completion section (Section 19.2: "the workshop pack
carries an ACORD alignment section for SMEs to complete manually"),
not silently omitted or faked.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from generated.C6.ConceptCluster._1_0 import C6Conceptcluster
from generated.C7.AlignmentRecord._1_0 import C7Alignmentrecord
from generated.C8.CanonicalCandidate._1_0 import C8Canonicalcandidate
from generated.C9.CoverageReport._1_0 import C9Coveragereport
from generated.C9.GapEntry._1_0 import C9Gapentry
from generated.C10.MappingSpec._1_0 import C10Mappingspec

from emit.common_schemas import build_common_schemas
from emit.logical_model import build_logical_model
from emit.openapi import build_openapi_projection
from emit.release import ReleaseManifest, validate_release_manifest
from emit.schema import build_entity_schemas, build_extension_schemas, serialise


@dataclass(frozen=True)
class PackFile:
    path: str
    sha256: str
    description: str


@dataclass(frozen=True)
class WorkshopPackManifest:
    domain: str
    version: str
    files: list[PackFile]
    declared_losses: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "domain": self.domain,
            "version": self.version,
            "files": [{"path": f.path, "sha256": f.sha256, "description": f.description} for f in self.files],
            "declaredLosses": self.declared_losses,
        }


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _write(output_dir: Path, relative_path: str, content: bytes, description: str) -> PackFile:
    destination = output_dir / relative_path
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(content)
    return PackFile(path=relative_path, sha256=_sha256(content), description=description)


def _yaml_bytes(doc: Any) -> bytes:
    text = yaml.safe_dump(doc, sort_keys=True, default_flow_style=False, allow_unicode=True)
    return text.encode("utf-8")


def _mapping_spec_with_tests(spec: C10Mappingspec, round_trip_summary: dict[str, Any] | None) -> dict[str, Any]:
    payload = spec.model_dump(mode="json", exclude_none=True)
    if round_trip_summary is not None:
        payload["tests"] = {"roundTrip": round_trip_summary}
    return payload


def _acord_manual_section(
    clusters: list[C6Conceptcluster], alignments: Mapping[str, C7Alignmentrecord]
) -> bytes:
    lines = [
        "# ACORD alignment - manual completion",
        "",
        "ACORD Reference Architecture data has been unavailable to this "
        "platform since Increment 1 (licence disposition never reached "
        "`permitted`). Every cluster below was assessed in Section 19.2's "
        "deterministic degraded mode (`verdict: unassessed`), not by the "
        "real ACORD Aligner agent. An SME with ACORD access should "
        "complete this section manually before the release is approved.",
        "",
        "| Cluster | Verdict | Notes |",
        "|---|---|---|",
    ]
    for cluster in clusters:
        record = alignments.get(str(cluster.clusterId))
        verdict = record.verdict.value if record is not None else "unassessed"
        lines.append(f"| {cluster.clusterId} | {verdict} | _SME to complete_ |")
    return ("\n".join(lines) + "\n").encode("utf-8")


def assemble_pack(
    output_dir: Path,
    *,
    domain: str,
    version: str,
    candidates: list[C8Canonicalcandidate],
    clusters: list[C6Conceptcluster],
    mapping_specs: Mapping[str, C10Mappingspec],
    round_trip_summaries: Mapping[str, dict[str, Any]],
    coverage_report: C9Coveragereport,
    gap_register: list[C9Gapentry],
    release_manifest: ReleaseManifest,
    evidence_by_candidate: Mapping[str, list[str]] | None = None,
    alignment_by_entity: Mapping[str, C7Alignmentrecord] | None = None,
    alignment_by_cluster: Mapping[str, C7Alignmentrecord] | None = None,
    owners: Mapping[str, str] | None = None,
) -> WorkshopPackManifest:
    evidence_by_candidate = evidence_by_candidate or {}
    alignment_by_cluster = alignment_by_cluster or {}
    files: list[PackFile] = []

    common_schemas = build_common_schemas(domain, version)
    for name, schema in sorted(common_schemas.items()):
        files.append(_write(output_dir, f"common/{name}.json", serialise(schema), f"Common {name} schema"))

    entity_schemas = build_entity_schemas(
        candidates, domain=domain, version=version, evidence_by_candidate=evidence_by_candidate
    )
    entity_schema_paths: dict[str, str] = {}
    for entity, schema in sorted(entity_schemas.items()):
        path = f"{entity}.json"
        entity_schema_paths[entity] = path
        files.append(_write(output_dir, path, serialise(schema), f"{entity} entity schema"))

    extension_schemas = build_extension_schemas(
        candidates, domain=domain, version=version, owners=owners, evidence_by_candidate=evidence_by_candidate
    )
    for (region, entity), schema in sorted(extension_schemas.items()):
        path = f"extensions/{region}/{entity}Extension.json"
        files.append(_write(output_dir, path, serialise(schema), f"{region.upper()} {entity} extension schema"))

    openapi_doc = build_openapi_projection(domain=domain, version=version, entity_schema_paths=entity_schema_paths)
    files.append(_write(output_dir, "openapi.yaml", _yaml_bytes(openapi_doc), "OpenAPI projection"))

    logical_model = build_logical_model(
        candidates,
        domain=domain,
        version=version,
        entity_schema_paths=entity_schema_paths,
        evidence_by_candidate=evidence_by_candidate,
        alignment_by_entity=alignment_by_entity,
    )
    files.append(_write(output_dir, "logical-model.jsonld", serialise(logical_model), "Logical model (JSON-LD)"))

    declared_losses: list[dict[str, Any]] = []
    for key, spec in sorted(mapping_specs.items()):
        summary = round_trip_summaries.get(key)
        payload = _mapping_spec_with_tests(spec, summary)
        files.append(
            _write(output_dir, f"mappings/{key}.mapping.json", serialise(payload), f"Mapping spec ({key}), source of truth")
        )
        files.append(
            _write(output_dir, f"mappings/{key}.mapping.yaml", _yaml_bytes(payload), f"Mapping spec ({key}), human-readable")
        )
        if summary is not None:
            for loss in summary.get("declaredLosses", []):
                declared_losses.append({"mappingSpec": key, **loss})
        for map_id, value_map in (spec.valueMaps or {}).items():
            files.append(
                _write(
                    output_dir,
                    f"valuemaps/{map_id}.yaml",
                    _yaml_bytes(value_map.model_dump(mode="json", exclude_none=True)),
                    f"Value map {map_id}",
                )
            )

    files.append(
        _write(
            output_dir,
            "coverage-report.json",
            serialise(coverage_report.model_dump(mode="json")),
            "Coverage report (Section 9.8)",
        )
    )
    files.append(
        _write(
            output_dir,
            "gap-register.json",
            serialise([g.model_dump(mode="json") for g in gap_register]),
            "Gap register (Section 9.8)",
        )
    )
    files.append(
        _write(
            output_dir,
            "acord-alignment.md",
            _acord_manual_section(clusters, alignment_by_cluster),
            "ACORD alignment - manual completion (Section 19.2 degraded mode)",
        )
    )

    manifest_dict = release_manifest.to_dict()
    validate_release_manifest(manifest_dict)
    files.append(_write(output_dir, "release-manifest.json", serialise(manifest_dict), "Release manifest (Section 11.4)"))

    files.sort(key=lambda f: f.path)
    manifest = WorkshopPackManifest(domain=domain, version=version, files=files, declared_losses=declared_losses)
    _write(output_dir, "workshop-pack-manifest.json", serialise(manifest.to_dict()), "This manifest")
    return manifest
