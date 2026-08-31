"""Utility Functions and Helpers

Shared utility code across the platform.
"""

import hashlib
from typing import Any, Dict
from uuid import UUID


def compute_hash(content: str) -> str:
    """Compute SHA256 hash of content."""
    return hashlib.sha256(content.encode()).hexdigest()


def normalize_attribute_name(name: str) -> str:
    """Normalize attribute name for comparison."""
    return name.lower().replace(" ", "_").replace("-", "_")


def merge_dicts(d1: Dict[str, Any], d2: Dict[str, Any]) -> Dict[str, Any]:
    """Recursively merge two dictionaries."""
    result = d1.copy()
    for key, value in d2.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = merge_dicts(result[key], value)
        else:
            result[key] = value
    return result


__all__ = [
    "compute_hash",
    "normalize_attribute_name",
    "merge_dicts",
]
