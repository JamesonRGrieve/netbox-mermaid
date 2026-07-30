# SPDX-License-Identifier: AGPL-3.0-or-later
"""netbox-cloudflare collector: the edge-delivery topology — cloudflared Tunnels (containers) with
their ingress rules and DNS records, and the account load-balancing chain (LoadBalancer → default
Pools → Origins, Pool → Monitor). Cloudflare is account/zone-scoped, not host-anchored, so it
populates only in whole-SoT (``all``) scope. WAF rules are omitted from the diagram for brevity and
live in full in the SoT report. Optional — skipped when the plugin is absent.
"""

from __future__ import annotations

from .base import Collector, Edge, Node, Scope, display, nid


class CloudflareCollector(Collector):
    app_label = "netbox_cloudflare"
    kind = "cftunnel"

    def collect(self, scope: Scope) -> tuple[list[Node], list[Edge]]:
        if scope.mode != "all":
            return [], []
        from netbox_cloudflare.models import (
            CloudflareIngress,
            CloudflareLBDefaultPool,
            CloudflareLBOrigin,
            CloudflareLBPool,
            CloudflareLoadBalancer,
            CloudflareMonitor,
            CloudflareRecord,
            CloudflareTunnel,
        )

        nodes: list[Node] = []
        edges: list[Edge] = []

        for tunnel in CloudflareTunnel.objects.all():
            nodes.append(Node(nid("cftunnel", tunnel.pk), display(tunnel, "name"), "cftunnel"))
        for ingress in CloudflareIngress.objects.all():
            label = ingress.hostname or "(catch-all)"
            nodes.append(
                Node(
                    nid("cfingress", ingress.pk),
                    label,
                    "cfingress",
                    parent=nid("cftunnel", ingress.tunnel_id),
                )
            )
        for record in CloudflareRecord.objects.all():
            parent = nid("cftunnel", record.tunnel_id) if record.tunnel_id else None
            nodes.append(
                Node(
                    nid("cfrecord", record.pk),
                    f"{record.name} [{record.type}]",
                    "cfrecord",
                    parent=parent,
                )
            )

        for monitor in CloudflareMonitor.objects.all():
            nodes.append(Node(nid("cfmonitor", monitor.pk), display(monitor, "name"), "cfmonitor"))
        for pool in CloudflareLBPool.objects.all():
            nodes.append(Node(nid("cfpool", pool.pk), display(pool, "name"), "cfpool"))
            if pool.monitor_id:
                edges.append(Edge(nid("cfpool", pool.pk), nid("cfmonitor", pool.monitor_id), "monitor"))
        for origin in CloudflareLBOrigin.objects.all():
            nodes.append(
                Node(
                    nid("cforigin", origin.pk),
                    display(origin, "name"),
                    "cforigin",
                    parent=nid("cfpool", origin.pool_id),
                )
            )
        for lb in CloudflareLoadBalancer.objects.all():
            nodes.append(Node(nid("cflb", lb.pk), display(lb, "name"), "cflb"))
            if lb.fallback_pool_id:
                edges.append(Edge(nid("cflb", lb.pk), nid("cfpool", lb.fallback_pool_id), "fallback"))
        for entry in CloudflareLBDefaultPool.objects.all():
            edges.append(
                Edge(nid("cflb", entry.load_balancer_id), nid("cfpool", entry.pool_id), "pool")
            )

        return nodes, edges
