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
from .dns import DnsCollector
from .email import EmailCollector
from .federation import FederationCollector
from .guests import GuestsCollector
from .logical import LogicalCollector
from .physical import PhysicalCollector
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
    # Physical (hypervisors, guests, cabling) and logical (VLANs, prefixes) topology views.
    PhysicalCollector(),
    LogicalCollector(),
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
    # Edge / delivery / load-balancing: name → address → load balancer → service.
    DnsCollector(),
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
    # Guest mounts / devices (netbox-guests).
    GuestsCollector(),
]


#: Collectors that scope themselves exactly (the spine and the topology views); every other
#: layer's output is anchored to their nodes under a tenant filter.
_SELF_SCOPED = frozenset({"core", "physical", "logical"})


def collect_all(scope: Scope) -> tuple[list[Node], list[Edge]]:
    """Collect + merge every available source drawn by ``scope.view``, within ``scope``."""
    anchors: list[Node] = []
    layered: list[Node] = []
    edges: list[Edge] = []
    for collector in COLLECTORS:
        if scope.view not in collector.views:
            continue
        collected_nodes, collected_edges = collector.safe_collect(scope)
        (anchors if collector.kind in _SELF_SCOPED else layered).extend(collected_nodes)
        edges.extend(collected_edges)
    if scope.tenant_id is not None:
        layered = anchor_to(anchors, layered, edges)
    if scope.view == "services":
        anchors = hosts_in_use(anchors, layered, edges)
    nodes = dedupe_nodes(anchors + layered)
    kept = {n.id for n in nodes}
    return nodes, [e for e in dedupe_edges(edges) if e.src in kept and e.dst in kept]


def anchor_to(anchors: list[Node], layered: list[Node], edges: list[Edge]) -> list[Node]:
    """The ``layered`` nodes that belong to a tenant window drawn by ``anchors``.

    Service-layer collectors scope by host, but global objects (an AI model catalog, a CA, a
    Cloudflare zone) carry no host and would otherwise flood a tenant diagram. Keep a layered node
    when it nests (at any depth) in an anchor, or is one edge from such a node — the catalog entry
    a tenant's deployment runs, the CA that issued its cert — together with that node's parents.
    """
    by_id = {n.id: n for n in layered}
    anchor_ids = {n.id for n in anchors}
    inside: dict[str, bool] = {}

    def nested(node_id: str, seen: frozenset[str] = frozenset()) -> bool:
        if node_id in anchor_ids:
            return True
        if node_id in inside:
            return inside[node_id]
        node = by_id.get(node_id)
        result = bool(
            node and node.parent and node.parent not in seen and nested(node.parent, seen | {node_id})
        )
        inside[node_id] = result
        return result

    kept = {n.id for n in layered if nested(n.id)}
    reach = anchor_ids | kept
    for edge in edges:
        for near, far in ((edge.src, edge.dst), (edge.dst, edge.src)):
            if near in reach and far in by_id:
                kept.add(far)
    for node_id in list(kept):  # parents of hop-in nodes, so they still sit in their container
        parent = by_id[node_id].parent
        while parent in by_id and parent not in kept:
            kept.add(parent)
            parent = by_id[parent].parent
    return [n for n in layered if n.id in kept]


#: Spine kinds the services view keeps only when something is drawn inside them.
_PRUNABLE_SPINE = frozenset({"device", "vm", "location"})


def hosts_in_use(anchors: list[Node], layered: list[Node], edges: list[Edge]) -> list[Node]:
    """The services view's spine without hosts (and racks/rooms) that take no part in it.

    A switch or an idle server says nothing about services; leaving it in only widens the
    diagram. A host is kept when a service-layer node is drawn inside it, or when it is one end
    of an edge from a service-layer node (the firewall a DNS name resolves to, the guest a load
    balancer routes to). With no service-layer data at all (no such plugin installed) nothing is
    pruned, so the view still shows the estate. Sites and tenants always stay, so the bounding
    boxes read the same as in other views.
    """
    if not layered:
        return anchors
    by_id = {n.id: n for n in anchors}
    layered_ids = {n.id for n in layered}
    starts = [n.parent for n in layered]
    for edge in edges:
        if edge.src in layered_ids or edge.dst in layered_ids:
            starts += [edge.src, edge.dst]
    used: set[str] = set()
    for start in starts:
        node_id = start
        while node_id in by_id and node_id not in used:
            used.add(node_id)
            node_id = by_id[node_id].parent
    return [n for n in anchors if n.kind not in _PRUNABLE_SPINE or n.id in used]
