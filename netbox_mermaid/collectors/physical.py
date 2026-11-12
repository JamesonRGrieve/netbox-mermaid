# SPDX-License-Identifier: AGPL-3.0-or-later
"""Physical-topology collector: the cabling between devices, and guest placement the spine can't
show by nesting. Core models only (``dcim`` / ``virtualization``), so it has no app-label guard.

Drawn by ``view=physical`` and ``view=all``. The core collector already nests every guest whose
hypervisor is known exactly inside that hypervisor's box, so this collector only adds:

* **cables** — one plain line (no arrowhead: a cable is symmetric) per pair of connected devices,
  labelled with every port pair on it (``1/46 ↔ nic0`` one per line), instead of one arrow per
  cable;
* **"can run on"** — for a guest on a multi-host cluster with no pinned device, an edge to each
  candidate hypervisor.
"""

from __future__ import annotations

from .base import Collector, Edge, Node, Scope, nid, vm_hosts, vm_site_id


class PhysicalCollector(Collector):
    """Device ↔ device cables (merged per device pair) and ambiguous-guest placement edges."""

    app_label = ""  # core models, always present
    kind = "physical"
    views = frozenset({"physical", "all"})

    def collect(self, scope: Scope) -> tuple[list[Node], list[Edge]]:
        from dcim.models import Cable
        from virtualization.models import VirtualMachine

        edges: list[Edge] = []

        # Guests whose hypervisor is ambiguous (multi-host cluster, no pinned device).
        cluster_cache: dict[int, list[int]] = {}
        for vm in VirtualMachine.objects.select_related("site", "cluster", "cluster___site"):
            if not scope.includes_vm(vm.pk, vm_site_id(vm)):
                continue
            hosts = vm_hosts(vm, cluster_cache)
            if len(hosts) > 1:
                for host in hosts:
                    edges.append(Edge(nid("vm", vm.pk), nid("dev", host), "can run on"))

        # Cables between device ports (interfaces, front/rear ports, console/power ports), merged
        # so each connected device pair gets one line listing all its port pairs.
        pairs: dict[tuple[int, int], list[str]] = {}
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
                    # Orient each pair low-pk → high-pk so A/B order never splits a pair.
                    if dev_a.pk < dev_b.pk:
                        key, text = (dev_a.pk, dev_b.pk), f"{port_a} ↔ {port_b}"
                    else:
                        key, text = (dev_b.pk, dev_a.pk), f"{port_b} ↔ {port_a}"
                    pairs.setdefault(key, []).append(text)
        for (low, high), ports in pairs.items():
            label = "\n".join(sorted(set(ports)))
            edges.append(Edge(nid("dev", low), nid("dev", high), label, style="line"))
        return [], edges
