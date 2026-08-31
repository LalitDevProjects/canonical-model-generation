"""
Section 11.1: "OpenAPI is a projection. The OpenAPI document references
the component schemas; it adds no type definitions of its own." Every
`components.schemas` entry here is a bare `$ref` into the already-emitted
entity schema documents (emit/schema.py) - never an inline type.

`paths` stays empty: Section 12's run-control/registry/workshop HTTP
service APIs are out of this 9-increment PoC's scope (api/README.md's own
Increment 12 deferral, unchanged since Increment 1), and nothing in this
projection's own job - documenting the emitted component *shapes* - needs
a live endpoint list.
"""

from __future__ import annotations

from typing import Any


def build_openapi_projection(
    *,
    domain: str,
    version: str,
    entity_schema_paths: dict[str, str],
) -> dict[str, Any]:
    """`entity_schema_paths` maps entity name -> relative file path (e.g.
    {"Claim": "Claim.json"}), matching whatever emit/workshop_pack.py
    actually wrote to disk alongside this document."""
    return {
        "openapi": "3.1.0",
        "info": {"title": f"{domain} canonical model", "version": version},
        "paths": {},
        "components": {
            "schemas": {
                entity: {"$ref": path} for entity, path in sorted(entity_schema_paths.items())
            }
        },
    }
