# SPDX-License-Identifier: AGPL-3.0-or-later
"""Logical-topology collector: VLANs (with their prefixes nested inside) and which hosts sit on
each. Core models only (``dcim`` / ``ipam`` / ``virtualization``), so it has no app-label guard.

A host joins a VLAN two ways, both drawn as an edge host → VLAN:

* **interface assignment** — a device interface's or VM interface's ``untagged_vlan`` ("untagged")
  or ``tagged_vlans`` ("tagged");
* **addressing** — an IP on one of the host's interfaces falls inside a prefix bound to the VLAN
  ("member" for a VM, "svi" for a device such as the router owning the VLAN's gateway).

Edge labels are verbs only: addresses appear solely as prefix node labels, which the sanitizer
redacts. Drawn by ``view=logical`` and ``view=all``.
"""

from __future__ import annotations

from .base import Collector, Edge, Node, Scope, nid, vm_site_id


class LogicalCollector(Collector):
    """VLAN containers (holding their prefixes) and host → VLAN membership edges."""

    app_label = ""  # core models, always present
    kind = "logical"
    views = frozenset({"logical", "all"})

    def collect(self, scope: Scope) -> tuple[list[Node], list[Edge]]:
        import netaddr
        from dcim.models import Interface
        from ipam.models import VLAN, IPAddress, Prefix
        from virtualization.models import VMInterface

        edges: list[Edge] = []
        vlan_ids: set[int] = set()

        def device_in(dev: object) -> bool:
            return dev is not None and scope.includes_device(dev.pk, dev.site_id)

        def vm_in(vm: object) -> bool:
            return vm is not None and scope.includes_vm(vm.pk, vm_site_id(vm))

        # Interface VLAN assignment (802.1Q mode on device and VM interfaces).
        for iface in Interface.objects.select_related("device").prefetch_related("tagged_vlans"):
            if not device_in(iface.device):
                continue
            host = nid("dev", iface.device_id)
            if iface.untagged_vlan_id:
                vlan_ids.add(iface.untagged_vlan_id)
                edges.append(Edge(host, nid("vlan", iface.untagged_vlan_id), "untagged"))
            for vlan in iface.tagged_vlans.all():
                vlan_ids.add(vlan.pk)
                edges.append(Edge(host, nid("vlan", vlan.pk), "tagged"))
        for iface in VMInterface.objects.select_related(
            "virtual_machine", "virtual_machine__cluster"
        ).prefetch_related("tagged_vlans"):
            if not vm_in(iface.virtual_machine):
                continue
            host = nid("vm", iface.virtual_machine_id)
            if iface.untagged_vlan_id:
                vlan_ids.add(iface.untagged_vlan_id)
                edges.append(Edge(host, nid("vlan", iface.untagged_vlan_id), "untagged"))
            for vlan in iface.tagged_vlans.all():
                vlan_ids.add(vlan.pk)
                edges.append(Edge(host, nid("vlan", vlan.pk), "tagged"))

        # Addressing: an assigned IP inside a VLAN-bound prefix puts its host on that VLAN
        # (longest-prefix match, so a /31 inside a /16 wins).
        vlan_prefixes = [
            (netaddr.IPNetwork(str(p.prefix)), p)
            for p in Prefix.objects.filter(vlan__isnull=False).select_related("vlan")
        ]
        vlan_prefixes.sort(key=lambda item: item[0].prefixlen, reverse=True)
        for ip in IPAddress.objects.filter(assigned_object_id__isnull=False).prefetch_related(
            "assigned_object"
        ):
            iface = ip.assigned_object
            device = getattr(iface, "device", None)
            vm = getattr(iface, "virtual_machine", None)
            if device is not None and device_in(device):
                host, verb = nid("dev", device.pk), "svi"
            elif vm is not None and vm_in(vm):
                host, verb = nid("vm", vm.pk), "member"
            else:
                continue
            addr = netaddr.IPAddress(str(ip.address.ip))
            for network, prefix in vlan_prefixes:
                if addr in network:
                    vlan_ids.add(prefix.vlan_id)
                    edges.append(Edge(host, nid("vlan", prefix.vlan_id), verb))
                    break

        # A tenant or site window also shows that tenant's / site's VLANs with no members yet.
        if scope.tenant_id is not None:
            vlan_ids.update(VLAN.objects.filter(tenant_id=scope.tenant_id).values_list("pk", flat=True))
        if scope.mode == "site":
            vlan_ids.update(VLAN.objects.filter(site_id=scope.site_id).values_list("pk", flat=True))

        nodes: list[Node] = []
        for vlan in VLAN.objects.filter(pk__in=vlan_ids):
            nodes.append(Node(nid("vlan", vlan.pk), f"VLAN {vlan.vid} {vlan.name}", "vlan"))
        for _network, prefix in vlan_prefixes:
            if prefix.vlan_id in vlan_ids:
                nodes.append(
                    Node(nid("prefix", prefix.pk), str(prefix.prefix), "prefix", parent=nid("vlan", prefix.vlan_id))
                )
        return nodes, edges
