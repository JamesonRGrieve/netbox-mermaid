# SPDX-License-Identifier: AGPL-3.0-or-later
"""netbox-zfs collector: ZFSPools (nested under their host device) and the ZFSVdevs that compose
them. Dataset / volume / vdev-member leaf detail is omitted from the diagram for brevity and lives
in full in the SoT report. A pool with no host (exported) becomes a top-level node. Optional —
skipped when the plugin is absent.
"""

from __future__ import annotations

from .base import Collector, Edge, Node, Scope, device_ref, display, nid


class ZfsCollector(Collector):
    app_label = "netbox_zfs"
    kind = "zfspool"

    def collect(self, scope: Scope) -> tuple[list[Node], list[Edge]]:
        from netbox_zfs.models import ZFSPool, ZFSVdev

        nodes: list[Node] = []
        included: set[int] = set()

        for pool in ZFSPool.objects.select_related("host", "host__site"):
            host_id, site_id = device_ref(pool.host)
            # An exported pool (no host) only shows in whole-SoT scope.
            if pool.host_id is None:
                if scope.mode != "all":
                    continue
            elif not scope.includes_device(pool.host_id, site_id):
                continue
            included.add(pool.pk)
            nodes.append(Node(nid("zfspool", pool.pk), display(pool, "name"), "zfspool", parent=host_id))

        for vdev in ZFSVdev.objects.filter(pool_id__in=included):
            nodes.append(
                Node(
                    nid("zfsvdev", vdev.pk),
                    f"{vdev.vdev_class} {vdev.redundancy} #{vdev.index}",
                    "zfsvdev",
                    parent=nid("zfspool", vdev.pool_id),
                )
            )

        return nodes, []
