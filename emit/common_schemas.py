"""
Section 11.1's `common/` bucket: shared sub-schemas referenced by every
entity schema (Party, PostalAddress, MonetaryAmount, ContactPoint,
DocumentRef, Identifier). Static, hand-authored content - these are not
derived from any C-contract or from candidates the way entity schemas
are (emit/schema.py::build_entity_schemas); they are a fixed part of the
canonical model's own vocabulary, one document per type, matching Section
11.1's own "One schema per type" rule.

MonetaryAmount and Identifier are shaped to match exactly what
mapping/transforms.py's own `toMonetaryAmount`/`toIdentifier` forward
functions produce ({amount, currency} / {value, scheme, issuer}) - the
same values these transforms emit are what a real mapping run writes into
a canonical instance, so the emitted schema and the actual runtime shape
agree by construction, not by convention alone.
"""

from __future__ import annotations

from typing import Any

_SCHEMA_BASE = "https://canonicalmodel.internal/canonical"


def _common_id(domain: str, version: str, name: str) -> str:
    return f"{_SCHEMA_BASE}/{domain}/{version}/common/{name}.json"


def build_common_schemas(domain: str, version: str) -> dict[str, dict[str, Any]]:
    """Returns {name: schema} for every common/ document (Section 11.1's
    worked layout example: Party, PostalAddress, MonetaryAmount,
    ContactPoint, DocumentRef, Identifier)."""
    return {
        "Party": {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": _common_id(domain, version, "Party"),
            "title": "Party",
            "type": "object",
            "additionalProperties": False,
            "required": ["partyType", "name"],
            "properties": {
                "partyType": {"type": "string", "enum": ["person", "organisation"]},
                "name": {"type": "string"},
                "identifiers": {"type": "array", "items": {"$ref": _common_id(domain, version, "Identifier")}},
            },
        },
        "PostalAddress": {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": _common_id(domain, version, "PostalAddress"),
            "title": "PostalAddress",
            "type": "object",
            "additionalProperties": False,
            "required": ["addressLine1", "postalCode", "countryCode"],
            "properties": {
                "addressLine1": {"type": "string"},
                "addressLine2": {"type": "string"},
                "city": {"type": "string"},
                "postalCode": {"type": "string"},
                "countryCode": {"type": "string"},
            },
        },
        "MonetaryAmount": {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": _common_id(domain, version, "MonetaryAmount"),
            "title": "MonetaryAmount",
            "type": "object",
            "additionalProperties": False,
            "required": ["amount", "currency"],
            "properties": {
                "amount": {"type": "number"},
                "currency": {"type": "string", "pattern": "^[A-Z]{3}$"},
            },
        },
        "ContactPoint": {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": _common_id(domain, version, "ContactPoint"),
            "title": "ContactPoint",
            "type": "object",
            "additionalProperties": False,
            "required": ["kind", "value"],
            "properties": {
                "kind": {"type": "string", "enum": ["email", "phone", "fax"]},
                "value": {"type": "string"},
            },
        },
        "DocumentRef": {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": _common_id(domain, version, "DocumentRef"),
            "title": "DocumentRef",
            "type": "object",
            "additionalProperties": False,
            "required": ["uri", "mediaType"],
            "properties": {
                "uri": {"type": "string"},
                "mediaType": {"type": "string"},
            },
        },
        "Identifier": {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": _common_id(domain, version, "Identifier"),
            "title": "Identifier",
            "type": "object",
            "additionalProperties": False,
            "required": ["value", "scheme", "issuer"],
            "properties": {
                "value": {"type": "string"},
                "scheme": {"type": "string"},
                "issuer": {"type": "string"},
            },
        },
    }
