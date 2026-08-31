"""Loader for golden/substrate/graph_fixture.json - not a conftest.py
(same reasoning as db_fixture.py: pytest needs that literal filename per
real conftest, and mypy can't tell two identically-named conftest.py
files in different directories apart when there's no __init__.py
anywhere under tests/)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import psycopg

from substrate.graph import write_edge, write_node


def load_graph_fixture(conn: psycopg.Connection, path: Path) -> dict[str, Any]:
    """Calls the exact same graph.write_node/write_edge functions
    substrate/ingest.py itself calls in production - this is real graph
    data, not a parallel test-only writer, even though its CONTENT is
    hand-authored rather than pipeline output."""
    payload: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    for node in payload["nodes"]:
        write_node(conn, node["node_id"], node["node_type"], node["properties"])
    for edge in payload["edges"]:
        write_edge(conn, edge["from_id"], edge["to_id"], edge["edge_type"], edge.get("properties"))
    return payload
