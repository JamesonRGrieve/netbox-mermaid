# SPDX-License-Identifier: AGPL-3.0-or-later
"""netbox-pf collector: the routing-shaped pf objects — Gateways and Gateway Groups (nested under
their device) with the group→gateway membership edges, plus named Aliases. Per-rule detail
(FirewallRule / NATRule / FirewallCategory) is intentionally omitted from the diagram for brevity —
it is exhaustively present in the SoT report. Optional — skipped when the plugin is absent.
"""

from __future__ import annotations

from .base import Collector, Edge, Node, Scope, device_ref, display, nid


class PfCollector(Collector):
    app_label = "netbox_pf"
    kind = "pfgw"

    def collect(self, scope: Scope) -> tuple[list[Node], list[Edge]]:
        from netbox_pf.models import Alias, Gateway, GatewayGroup, GatewayGroupMember

        nodes: list[Node] = []
        edges: list[Edge] = []

        for gw in Gateway.objects.select_related("device", "device__site"):
            host_id, site_id = device_ref(gw.device)
            if not scope.includes_device(gw.device_id, site_id):
                continue
            nodes.append(Node(nid("pfgw", gw.pk), display(gw, "name"), "pfgw", parent=host_id))

        for group in GatewayGroup.objects.select_related("device", "device__site"):
            host_id, site_id = device_ref(group.device)
            if not scope.includes_device(group.device_id, site_id):
                continue
            nodes.append(
                Node(nid("pfgwgroup", group.pk), display(group, "name"), "pfgwgroup", parent=host_id)
            )

        for member in GatewayGroupMember.objects.all():
            edges.append(
                Edge(
                    nid("pfgwgroup", member.group_id),
                    nid("pfgw", member.gateway_id),
                    f"tier {member.tier}",
                )
            )

        if scope.mode == "all":
            for alias in Alias.objects.all():
                nodes.append(Node(nid("pfalias", alias.pk), display(alias, "name"), "pfalias"))

        return nodes, edges
