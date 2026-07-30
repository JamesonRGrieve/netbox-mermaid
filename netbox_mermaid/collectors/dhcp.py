# SPDX-License-Identifier: AGPL-3.0-or-later
"""netbox-dhcp collector: the DHCP servers a device runs — v4 DHCPScopes, v6 subnets, and v6 HA
peers — each nested under its device. Per-scope leaf detail (reservations, options, PD pools) is
omitted from the diagram for brevity and lives in full in the SoT report. Optional — skipped when
the plugin is absent.
"""

from __future__ import annotations

from .base import Collector, Edge, Node, Scope, device_ref, display, nid

_SELECT = ("device", "device__site")


class DhcpCollector(Collector):
    app_label = "netbox_dhcp"
    kind = "dhcp"

    def collect(self, scope: Scope) -> tuple[list[Node], list[Edge]]:
        from netbox_dhcp.models import DHCPScope, DHCPv6Peer, DHCPv6Subnet

        nodes: list[Node] = []

        for scope_row in DHCPScope.objects.select_related(*_SELECT):
            host_id, site_id = device_ref(scope_row.device)
            if not scope.includes_device(scope_row.device_id, site_id):
                continue
            nodes.append(
                Node(nid("dhcp", scope_row.pk), display(scope_row, "name"), "dhcp", parent=host_id)
            )

        for subnet in DHCPv6Subnet.objects.select_related(*_SELECT):
            host_id, site_id = device_ref(subnet.device)
            if not scope.includes_device(subnet.device_id, site_id):
                continue
            nodes.append(
                Node(nid("dhcp6", subnet.pk), display(subnet, "name"), "dhcp", parent=host_id)
            )

        for peer in DHCPv6Peer.objects.select_related(*_SELECT):
            host_id, site_id = device_ref(peer.device)
            if not scope.includes_device(peer.device_id, site_id):
                continue
            nodes.append(
                Node(nid("dhcp6peer", peer.pk), display(peer, "name"), "dhcp", parent=host_id)
            )

        return nodes, []
