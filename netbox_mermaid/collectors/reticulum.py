# SPDX-License-Identifier: AGPL-3.0-or-later
"""netbox-reticulum collector: ReticulumNodes nested under their host (a device XOR a VM), each with
a ``network`` edge to the ReticulumNetwork they join. A node with no host nests under its network.
Interface / destination leaf detail is omitted from the diagram for brevity and lives in full in the
SoT report. Optional — skipped when the plugin is absent.
"""

from __future__ import annotations

from .base import Collector, Edge, Node, Scope, display, dual_host_in_scope, dual_host_ref, nid

_SELECT = ("host_device", "host_device__site", "host_vm", "host_vm__site", "reticulum_network")


class ReticulumCollector(Collector):
    app_label = "netbox_reticulum"
    kind = "retnode"

    def collect(self, scope: Scope) -> tuple[list[Node], list[Edge]]:
        from netbox_reticulum.models import ReticulumNetwork, ReticulumNode

        nodes: list[Node] = []
        edges: list[Edge] = []

        if scope.mode == "all":
            for net in ReticulumNetwork.objects.all():
                nodes.append(Node(nid("retnet", net.pk), display(net, "name"), "retnet"))

        for node in ReticulumNode.objects.select_related(*_SELECT):
            if not dual_host_in_scope(scope, node):
                continue
            host_id, _ = dual_host_ref(node)
            # No host resolvable: nest under the network (only present in whole-SoT scope).
            parent = host_id or (nid("retnet", node.reticulum_network_id) if scope.mode == "all" else None)
            if parent is None:
                continue
            nodes.append(Node(nid("retnode", node.pk), display(node, "name"), "retnode", parent=parent))
            if host_id and node.reticulum_network_id:
                edges.append(Edge(nid("retnode", node.pk), nid("retnet", node.reticulum_network_id), "network"))

        return nodes, edges
