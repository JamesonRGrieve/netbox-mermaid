# SPDX-License-Identifier: AGPL-3.0-or-later
"""netbox-database collector: DatabaseServer (nested under its host), its logical Databases /
Users, DatabaseGrant user→database edges, the server→ServiceInstance link, and Galera / Postgres
cluster-membership edges. Optional — skipped when the plugin is absent.
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


class DatabaseCollector(Collector):
    app_label = "netbox_database"
    kind = "dbserver"

    def collect(self, scope: Scope) -> tuple[list[Node], list[Edge]]:
        from netbox_database.models import (
            Database,
            DatabaseGrant,
            DatabaseServer,
            DatabaseUser,
            GaleraNode,
            PostgresClusterNode,
        )

        nodes: list[Node] = []
        edges: list[Edge] = []
        included: set[int] = set()

        servers = DatabaseServer.objects.select_related("service_instance", *_HOST_SELECT)
        for server in servers:
            if not host_in_scope(scope, server):
                continue
            included.add(server.pk)
            host_id, _ = host_ref(server)
            nodes.append(
                Node(
                    nid("dbserver", server.pk),
                    server.name,
                    "dbserver",
                    parent=host_id,
                    raw_attrs={"engine": str(server.engine), "version": str(server.version)},
                )
            )
            if server.service_instance_id:
                edges.append(
                    Edge(
                        nid("dbserver", server.pk),
                        nid("svc", server.service_instance_id),
                        "service",
                    )
                )

        for db in Database.objects.filter(server_id__in=included):
            nodes.append(
                Node(nid("db", db.pk), db.name, "database", parent=nid("dbserver", db.server_id))
            )
        for user in DatabaseUser.objects.filter(server_id__in=included):
            nodes.append(
                Node(
                    nid("dbuser", user.pk),
                    user.username,
                    "dbuser",
                    parent=nid("dbserver", user.server_id),
                )
            )
        for grant in DatabaseGrant.objects.filter(user__server_id__in=included):
            edges.append(Edge(nid("dbuser", grant.user_id), nid("db", grant.database_id), "grants"))

        clusters: dict[str, str] = {}
        for gnode in GaleraNode.objects.select_related("cluster").filter(server_id__in=included):
            cid = nid("galera", gnode.cluster_id)
            clusters[cid] = gnode.cluster.name
            edges.append(Edge(nid("dbserver", gnode.server_id), cid, "galera member"))
        for pnode in PostgresClusterNode.objects.select_related("cluster").filter(
            server_id__in=included
        ):
            cid = nid("pgcluster", pnode.cluster_id)
            clusters[cid] = pnode.cluster.name
            edges.append(Edge(nid("dbserver", pnode.server_id), cid, "postgres member"))
        for cid, name in clusters.items():
            nodes.append(Node(cid, name, "cluster"))

        return nodes, edges
