# SPDX-License-Identifier: AGPL-3.0-or-later
"""netbox-wireguard collector: WireGuardTunnel (nested under its device) with its WireGuardPeers
nested beneath. Non-secret shape only — the plugin never stores key material. Optional — skipped
when the plugin is absent.
"""

from __future__ import annotations

from .base import Collector, Edge, Node, Scope, device_ref, display, nid


class WireGuardCollector(Collector):
    app_label = "netbox_wireguard"
    kind = "wgtunnel"

    def collect(self, scope: Scope) -> tuple[list[Node], list[Edge]]:
        from netbox_wireguard.models import WireGuardPeer, WireGuardTunnel

        nodes: list[Node] = []
        included: set[int] = set()

        for tunnel in WireGuardTunnel.objects.select_related("device", "device__site"):
            host_id, site_id = device_ref(tunnel.device)
            if not scope.includes_device(tunnel.device_id, site_id):
                continue
            included.add(tunnel.pk)
            nodes.append(
                Node(nid("wgtunnel", tunnel.pk), display(tunnel, "name"), "wgtunnel", parent=host_id)
            )

        for peer in WireGuardPeer.objects.filter(tunnel_id__in=included):
            nodes.append(
                Node(
                    nid("wgpeer", peer.pk),
                    display(peer, "name"),
                    "wgpeer",
                    parent=nid("wgtunnel", peer.tunnel_id),
                )
            )

        return nodes, []
