# SPDX-License-Identifier: AGPL-3.0-or-later
"""Collector registry — the single extensibility point.

``COLLECTORS`` lists every source collector in render order (core spine first, then the optional
plugin layers). :func:`collect_all` runs each through its :meth:`Collector.safe_collect` guard, so
an absent or incompatible plugin contributes nothing rather than failing the diagram, then merges
and de-duplicates. **Adding a new source is a one-file drop-in**: write a ``Collector`` subclass in
this package and append its instance here — nothing else changes.
"""

from __future__ import annotations

from .base import Collector, Edge, Node, Scope, dedupe_edges, dedupe_nodes
from .core import CoreCollector
from .database import DatabaseCollector
from .email import EmailCollector
from .federation import FederationCollector
from .pki import PkiCollector
from .services import ServicesCollector
from .webserver import WebServerCollector
from .wordpress import WordPressCollector

COLLECTORS: list[Collector] = [
    CoreCollector(),
    ServicesCollector(),
    DatabaseCollector(),
    WebServerCollector(),
    WordPressCollector(),
    PkiCollector(),
    EmailCollector(),
    FederationCollector(),
]


def collect_all(scope: Scope) -> tuple[list[Node], list[Edge]]:
    """Collect + merge every available source within ``scope``."""
    nodes: list[Node] = []
    edges: list[Edge] = []
    for collector in COLLECTORS:
        collected_nodes, collected_edges = collector.safe_collect(scope)
        nodes.extend(collected_nodes)
        edges.extend(collected_edges)
    return dedupe_nodes(nodes), dedupe_edges(edges)
