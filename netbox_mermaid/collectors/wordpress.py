# SPDX-License-Identifier: AGPL-3.0-or-later
"""netbox-wordpress collector: WordPressSite (nested under its host) with its labelled cross-links
to the backing Database, DatabaseUser, ServiceInstance, and object-cache instance, plus its
installed plugins/themes as nested detail. Optional — skipped when the plugin is absent.
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


class WordPressCollector(Collector):
    app_label = "netbox_wordpress"
    kind = "wpsite"

    def collect(self, scope: Scope) -> tuple[list[Node], list[Edge]]:
        from netbox_wordpress.models import WordPressPlugin, WordPressSite, WordPressTheme

        nodes: list[Node] = []
        edges: list[Edge] = []
        included: set[int] = set()

        for site in WordPressSite.objects.select_related(*_HOST_SELECT):
            if not host_in_scope(scope, site):
                continue
            included.add(site.pk)
            host_id, _ = host_ref(site)
            nodes.append(Node(nid("wp", site.pk), site.name, "wpsite", parent=host_id))
            if site.database_id:
                edges.append(Edge(nid("wp", site.pk), nid("db", site.database_id), "db"))
            if site.db_user_id:
                edges.append(Edge(nid("wp", site.pk), nid("dbuser", site.db_user_id), "db user"))
            if site.service_instance_id:
                edges.append(
                    Edge(nid("wp", site.pk), nid("svc", site.service_instance_id), "service")
                )
            if site.object_cache_instance_id:
                edges.append(
                    Edge(nid("wp", site.pk), nid("svc", site.object_cache_instance_id), "cache")
                )

        for plugin in WordPressPlugin.objects.filter(site_id__in=included):
            nodes.append(
                Node(
                    nid("wpplug", plugin.pk),
                    plugin.slug,
                    "wpcomponent",
                    parent=nid("wp", plugin.site_id),
                )
            )
        for theme in WordPressTheme.objects.filter(site_id__in=included):
            nodes.append(
                Node(
                    nid("wptheme", theme.pk),
                    theme.slug,
                    "wpcomponent",
                    parent=nid("wp", theme.site_id),
                )
            )

        return nodes, edges
