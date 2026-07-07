# SPDX-License-Identifier: AGPL-3.0-or-later
"""netbox-federation collector: FederationRealms (nested under the ServiceInstance that serves
them) with their FederationPeers nested beneath. Not host-anchored, so it populates only in
whole-SoT (``all``) scope. Optional — skipped when the plugin is absent.
"""

from __future__ import annotations

from .base import Collector, Edge, Node, Scope, nid


class FederationCollector(Collector):
    app_label = "netbox_federation"
    kind = "realm"

    def collect(self, scope: Scope) -> tuple[list[Node], list[Edge]]:
        if scope.mode != "all":
            return [], []
        from netbox_federation.models import FederationPeer, FederationRealm

        nodes: list[Node] = []
        edges: list[Edge] = []

        for realm in FederationRealm.objects.all():
            parent = nid("svc", realm.service_instance_id) if realm.service_instance_id else None
            nodes.append(Node(nid("realm", realm.pk), realm.name, "realm", parent=parent))
        for peer in FederationPeer.objects.all():
            nodes.append(
                Node(
                    nid("peer", peer.pk),
                    peer.peer_domain,
                    "peer",
                    parent=nid("realm", peer.realm_id),
                )
            )

        return nodes, edges
