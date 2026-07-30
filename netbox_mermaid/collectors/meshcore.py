# SPDX-License-Identifier: AGPL-3.0-or-later
"""netbox-meshcore collector: MeshNodes (radios) grouped under their MeshNetwork, with observed
MeshLink edges between node pairs. A companion node bound to a host (device XOR VM) nests under that
host instead, keeping its ``mesh`` edge to the network. ACL-entry leaf detail is omitted from the
diagram for brevity and lives in full in the SoT report. Optional — skipped when the plugin is
absent.
"""

from __future__ import annotations

from .base import Collector, Edge, Node, Scope, display, dual_host_in_scope, dual_host_ref, nid

_SELECT = ("host_device", "host_device__site", "host_vm", "host_vm__site", "mesh_network")


class MeshCoreCollector(Collector):
    app_label = "netbox_meshcore"
    kind = "meshnode"

    def collect(self, scope: Scope) -> tuple[list[Node], list[Edge]]:
        from netbox_meshcore.models import MeshLink, MeshNetwork, MeshNode

        nodes: list[Node] = []
        edges: list[Edge] = []
        included: set[int] = set()

        if scope.mode == "all":
            for net in MeshNetwork.objects.all():
                nodes.append(Node(nid("meshnet", net.pk), display(net, "name"), "meshnet"))

        for node in MeshNode.objects.select_related(*_SELECT):
            if not dual_host_in_scope(scope, node):
                continue
            host_id, _ = dual_host_ref(node)
            parent = host_id or (nid("meshnet", node.mesh_network_id) if scope.mode == "all" else None)
            if parent is None:
                continue
            included.add(node.pk)
            nodes.append(Node(nid("meshnode", node.pk), display(node, "name"), "meshnode", parent=parent))
            if host_id and node.mesh_network_id:
                edges.append(Edge(nid("meshnode", node.pk), nid("meshnet", node.mesh_network_id), "mesh"))

        for link in MeshLink.objects.filter(a_id__in=included, b_id__in=included):
            edges.append(Edge(nid("meshnode", link.a_id), nid("meshnode", link.b_id), "link"))

        return nodes, edges
