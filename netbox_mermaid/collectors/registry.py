# SPDX-License-Identifier: AGPL-3.0-or-later
"""Collector registry — the single extensibility point.

``COLLECTORS`` lists every source collector in render order (core spine first, then the optional
plugin layers). :func:`collect_all` runs each through its :meth:`Collector.safe_collect` guard, so
an absent or incompatible plugin contributes nothing rather than failing the diagram, then merges
and de-duplicates. **Adding a new source is a one-file drop-in**: write a ``Collector`` subclass in
this package and append its instance here — nothing else changes.
"""

from __future__ import annotations

from .ai import AiCollector
from .base import Collector, Edge, Node, Scope, dedupe_edges, dedupe_nodes
from .cloudflare import CloudflareCollector
from .core import CoreCollector
from .database import DatabaseCollector
from .datalink import DataLinkCollector
from .dhcp import DhcpCollector
from .email import EmailCollector
from .federation import FederationCollector
from .guests import GuestsCollector
from .hostrole import HostRoleCollector
from .lb_acl import LbAclCollector
from .meshcore import MeshCoreCollector
from .pf import PfCollector
from .pki import PkiCollector
from .reticulum import ReticulumCollector
from .services import ServicesCollector
from .webserver import WebServerCollector
from .wireguard import WireGuardCollector
from .wordpress import WordPressCollector
from .zfs import ZfsCollector

COLLECTORS: list[Collector] = [
    # Core spine.
    CoreCollector(),
    # Service / application layer.
    ServicesCollector(),
    HostRoleCollector(),
    DatabaseCollector(),
    WebServerCollector(),
    WordPressCollector(),
    AiCollector(),
    # PKI / mail / federation.
    PkiCollector(),
    EmailCollector(),
    FederationCollector(),
    # Edge / delivery / load-balancing.
    CloudflareCollector(),
    LbAclCollector(),
    # Networking layer (firewall, DHCP, VPN, mesh).
    PfCollector(),
    DhcpCollector(),
    DataLinkCollector(),
    WireGuardCollector(),
    ReticulumCollector(),
    MeshCoreCollector(),
    # Storage.
    ZfsCollector(),
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
