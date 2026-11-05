# SPDX-License-Identifier: AGPL-3.0-or-later
"""Physical-topology collector: which hypervisor each guest runs on, and the cabling between
devices. Core models only (``dcim`` / ``virtualization``), so it has no app-label guard.

Drawn by ``view=physical`` and ``view=all``. The device/VM vertices themselves come from the core
collector; this one adds the edges between them, so a scope that leaves one end out simply drops
that edge in the builder.
"""

from __future__ import annotations

from .base import Collector, Edge, Node, Scope, nid, vm_site_id


class PhysicalCollector(Collector):
    """VM → hosting device ("runs on") and device ↔ device cables ("cable <a> ↔ <b>")."""

    app_label = ""  # core models, always present
    kind = "physical"
    views = frozenset({"physical", "all"})

    def collect(self, scope: Scope) -> tuple[list[Node], list[Edge]]:
        from dcim.models import Cable, Device
        from virtualization.models import VirtualMachine

        edges: list[Edge] = []

        # Guests → the hypervisor(s) they run on: the VM's own device when set, else every device
        # of its cluster (a VM pinned to no device can run on any of them).
        cluster_devices: dict[int, list[int]] = {}
        for vm in VirtualMachine.objects.select_related("site", "cluster", "cluster___site"):
            if not scope.includes_vm(vm.pk, vm_site_id(vm)):
                continue
            if vm.device_id:
                hosts = [vm.device_id]
            elif vm.cluster_id:
                if vm.cluster_id not in cluster_devices:
                    cluster_devices[vm.cluster_id] = list(
                        Device.objects.filter(cluster_id=vm.cluster_id).values_list("pk", flat=True)
                    )
                hosts = cluster_devices[vm.cluster_id]
            else:
                hosts = []
            for host in hosts:
                edges.append(Edge(nid("vm", vm.pk), nid("dev", host), "runs on"))

        # Cables between device ports (interfaces, front/rear ports, console/power ports): one edge
        # per A-end × B-end pair of distinct devices, labelled with both port names.
        for cable in Cable.objects.prefetch_related("terminations__termination"):
            ends: dict[str, list[tuple[object, str]]] = {"A": [], "B": []}
            for term in cable.terminations.all():
                port = term.termination
                device = getattr(port, "device", None)
                if device is None or term.cable_end not in ends:
                    continue
                ends[term.cable_end].append((device, getattr(port, "name", "") or ""))
            for dev_a, port_a in ends["A"]:
                for dev_b, port_b in ends["B"]:
                    if dev_a.pk == dev_b.pk:
                        continue
                    if not (
                        scope.includes_device(dev_a.pk, dev_a.site_id)
                        and scope.includes_device(dev_b.pk, dev_b.site_id)
                    ):
                        continue
                    edges.append(
                        Edge(nid("dev", dev_a.pk), nid("dev", dev_b.pk), f"cable {port_a} ↔ {port_b}")
                    )
        return [], edges
