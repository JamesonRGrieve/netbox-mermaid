# SPDX-License-Identifier: AGPL-3.0-or-later
"""netbox-webserver collector: WebServer (nested under its host), its VirtualHosts and PHP-FPM
pools as nested detail, and the server→ServiceInstance link. The VirtualHost cert linkage is a
``cert_ref`` **path string** (not a relational FK), so it is carried in ``raw_attrs`` (dropped by
the sanitizer) rather than emitted as a cross-edge. Optional — skipped when the plugin is absent.
"""

from __future__ import annotations

from .base import Collector, Edge, Node, Scope, host_in_scope, host_ref, nid

_HOST_SELECT = (
    "device",
    "device__site",
    "virtual_machine",
    "virtual_machine__site",
    "virtual_machine__cluster",
    "virtual_machine__cluster__site",
)


class WebServerCollector(Collector):
    app_label = "netbox_webserver"
    kind = "webserver"

    def collect(self, scope: Scope) -> tuple[list[Node], list[Edge]]:
        from netbox_webserver.models import PHPFPMPool, VirtualHost, WebServer

        nodes: list[Node] = []
        edges: list[Edge] = []
        included: set[int] = set()

        for server in WebServer.objects.select_related("service_instance", *_HOST_SELECT):
            if not host_in_scope(scope, server):
                continue
            included.add(server.pk)
            host_id, _ = host_ref(server)
            nodes.append(Node(nid("web", server.pk), server.name, "webserver", parent=host_id))
            if server.service_instance_id:
                edges.append(
                    Edge(nid("web", server.pk), nid("svc", server.service_instance_id), "service")
                )

        for vhost in VirtualHost.objects.filter(server_id__in=included):
            nodes.append(
                Node(
                    nid("vhost", vhost.pk),
                    vhost.server_name,
                    "vhost",
                    parent=nid("web", vhost.server_id),
                    raw_attrs={"cert_ref": str(vhost.cert_ref or "")},
                )
            )
        for pool in PHPFPMPool.objects.filter(server_id__in=included):
            nodes.append(
                Node(nid("fpm", pool.pk), pool.name, "fpmpool", parent=nid("web", pool.server_id))
            )

        return nodes, edges
