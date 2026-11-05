# SPDX-License-Identifier: AGPL-3.0-or-later
"""Core-NetBox collector: Sites (containers), Devices, Virtual Machines, and their Tenants.

``dcim`` / ``virtualization`` / ``tenancy`` are always installed, so this collector has no app-label
guard — it is the structural spine every plugin collector nests its objects onto.
"""

from __future__ import annotations

from .base import VIEWS, Collector, Edge, Node, Scope, nid, vm_site_id


class CoreCollector(Collector):
    """Sites → Devices / VMs → Tenants. The container hierarchy the plugin layers hang from."""

    app_label = ""  # core is always present
    kind = "core"
    views = frozenset(VIEWS)  # the structural spine every view hangs from

    def collect(self, scope: Scope) -> tuple[list[Node], list[Edge]]:
        from dcim.models import Device, Site
        from django.db.models import Q
        from virtualization.models import VirtualMachine

        nodes: list[Node] = []
        edges: list[Edge] = []
        container_site_ids: set[int] = set()
        tenants: dict[int, str] = {}

        devices = Device.objects.select_related("site", "tenant")
        if scope.mode == "device":
            devices = devices.filter(pk=scope.device_id)
        elif scope.mode == "site":
            devices = devices.filter(site_id=scope.site_id)
        elif scope.mode == "vm":
            devices = devices.none()
        tenant_devices = scope.tenant_device_ids()
        if tenant_devices is not None:
            devices = devices.filter(pk__in=tenant_devices)
        for dev in devices:
            if not scope.includes_device(dev.pk, dev.site_id):
                continue
            parent = nid("site", dev.site_id) if dev.site_id else None
            nodes.append(
                Node(nid("dev", dev.pk), dev.name or f"device {dev.pk}", "device", parent=parent)
            )
            if dev.site_id:
                container_site_ids.add(dev.site_id)
            if dev.tenant_id:
                tenants[dev.tenant_id] = dev.tenant.name
                edges.append(Edge(nid("dev", dev.pk), nid("tenant", dev.tenant_id), "tenant"))

        vms = VirtualMachine.objects.select_related("site", "cluster", "cluster___site", "tenant")
        if scope.mode == "vm":
            vms = vms.filter(pk=scope.vm_id)
        elif scope.mode == "site":
            vms = vms.filter(Q(site_id=scope.site_id) | Q(cluster___site_id=scope.site_id))
        elif scope.mode == "device":
            vms = vms.none()
        tenant_vms = scope.tenant_vm_ids()
        if tenant_vms is not None:
            vms = vms.filter(pk__in=tenant_vms)
        for vm in vms:
            site_id = vm_site_id(vm)
            if not scope.includes_vm(vm.pk, site_id):
                continue
            parent = nid("site", site_id) if site_id else None
            nodes.append(Node(nid("vm", vm.pk), vm.name or f"vm {vm.pk}", "vm", parent=parent))
            if site_id:
                container_site_ids.add(site_id)
            if vm.tenant_id:
                tenants[vm.tenant_id] = vm.tenant.name
                edges.append(Edge(nid("vm", vm.pk), nid("tenant", vm.tenant_id), "tenant"))

        # A tenant filter draws only the sites holding that tenant's hosts (never every site).
        if scope.mode in ("all", "site") and scope.tenant_id is None:
            sites = Site.objects.all()
            if scope.mode == "site":
                sites = sites.filter(pk=scope.site_id)
            for site in sites:
                nodes.append(Node(nid("site", site.pk), site.name, "site"))
        elif container_site_ids:
            for site in Site.objects.filter(pk__in=container_site_ids):
                nodes.append(Node(nid("site", site.pk), site.name, "site"))

        for tenant_id, tenant_name in tenants.items():
            nodes.append(Node(nid("tenant", tenant_id), tenant_name, "tenant"))

        return nodes, edges
