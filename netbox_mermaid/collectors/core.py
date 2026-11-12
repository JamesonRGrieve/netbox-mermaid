# SPDX-License-Identifier: AGPL-3.0-or-later
"""Core-NetBox collector: the structural spine every view hangs from.

Tenant box → Site box → Location box(es) → Devices → (physical/all views) the guests they host.

* A **tenant** is a bounding box around its sites, never an edge target: with a tenant filter the
  tenant box wraps every site drawn; without one, a site that has a tenant sits inside that box.
* **Locations** nest inside their site (and inside their parent location), holding their devices.
* In the ``physical`` / ``services`` / ``all`` views a VM nests inside the hypervisor running it (its own
  ``device``, else its cluster's only device), so "runs on" needs no edge. A VM on a multi-host
  cluster with no pinned device stays in its site box.
* The ``logical`` view draws no hosts here: they appear inside the VLAN cards (see ``logical.py``).

``dcim`` / ``virtualization`` / ``tenancy`` are always installed, so there is no app-label guard.
"""

from __future__ import annotations

from .base import VIEWS, Collector, Edge, Node, Scope, nid, vm_hosts, vm_site_id

#: Views in which guests nest inside the hypervisor that runs them.
_HOST_NESTING_VIEWS = frozenset({"physical", "services", "all"})


def _ip(obj: object) -> str:
    """The object's primary IPv4 (else IPv6) address without the mask, or ``""``."""
    for attr in ("primary_ip4", "primary_ip6"):
        ip = getattr(obj, attr, None)
        if ip is not None:
            return str(ip.address.ip)
    return ""


def device_label(dev: object) -> str:
    """``name`` over ``role · primary IP`` (each line only when known)."""
    detail = " · ".join(p for p in (getattr(getattr(dev, "role", None), "name", ""), _ip(dev)) if p)
    name = dev.name or f"device {dev.pk}"
    return f"{name}\n{detail}" if detail else name


def vm_label(vm: object) -> str:
    """``name`` over its primary IP (when it has one)."""
    name = vm.name or f"vm {vm.pk}"
    address = _ip(vm)
    return f"{name}\n{address}" if address else name


class CoreCollector(Collector):
    """Tenant → Site → Location → Device (→ guest) containers, the hierarchy every layer hangs from."""

    app_label = ""  # core is always present
    kind = "core"
    views = frozenset(VIEWS)  # the structural spine every view hangs from

    def collect(self, scope: Scope) -> tuple[list[Node], list[Edge]]:
        from dcim.models import Device, Location, Site
        from django.db.models import Q
        from virtualization.models import VirtualMachine

        nodes: list[Node] = []
        draw_hosts = scope.view != "logical"
        nest_guests = scope.view in _HOST_NESTING_VIEWS
        site_ids: set[int] = set()
        location_ids: set[int] = set()
        drawn_devices: set[int] = set()

        devices = Device.objects.select_related(
            "site", "location", "role", "primary_ip4", "primary_ip6"
        )
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
            if dev.site_id:
                site_ids.add(dev.site_id)
            if dev.location_id:
                location_ids.add(dev.location_id)
            if not draw_hosts:
                continue
            if dev.location_id:
                parent = nid("loc", dev.location_id)
            else:
                parent = nid("site", dev.site_id) if dev.site_id else None
            nodes.append(Node(nid("dev", dev.pk), device_label(dev), "device", parent=parent))
            drawn_devices.add(dev.pk)

        vms = VirtualMachine.objects.select_related(
            "site", "cluster", "cluster___site", "primary_ip4", "primary_ip6"
        )
        if scope.mode == "vm":
            vms = vms.filter(pk=scope.vm_id)
        elif scope.mode == "site":
            vms = vms.filter(Q(site_id=scope.site_id) | Q(cluster___site_id=scope.site_id))
        elif scope.mode == "device":
            vms = vms.none()
        tenant_vms = scope.tenant_vm_ids()
        if tenant_vms is not None:
            vms = vms.filter(pk__in=tenant_vms)
        cluster_hosts: dict[int, list[int]] = {}
        for vm in vms:
            site_id = vm_site_id(vm)
            if not scope.includes_vm(vm.pk, site_id):
                continue
            if site_id:
                site_ids.add(site_id)
            if not draw_hosts:
                continue
            parent = nid("site", site_id) if site_id else None
            if nest_guests:
                hosts = vm_hosts(vm, cluster_hosts)
                if len(hosts) == 1 and hosts[0] in drawn_devices:
                    parent = nid("dev", hosts[0])
            nodes.append(Node(nid("vm", vm.pk), vm_label(vm), "vm", parent=parent))

        # Sites. A tenant filter draws only the sites holding that tenant's hosts (never every
        # site); an unfiltered whole-SoT / site window draws every site in the window.
        if scope.mode in ("all", "site") and scope.tenant_id is None:
            sites = Site.objects.select_related("tenant")
            if scope.mode == "site":
                sites = sites.filter(pk=scope.site_id)
        else:
            sites = Site.objects.select_related("tenant").filter(pk__in=site_ids)
        tenant_box = nid("tenant", scope.tenant_id) if scope.tenant_id else None
        tenants: dict[int, str] = {}
        for site in sites:
            if tenant_box:
                parent = tenant_box
            elif site.tenant_id:
                parent = nid("tenant", site.tenant_id)
                tenants[site.tenant_id] = site.tenant.name
            else:
                parent = None
            nodes.append(Node(nid("site", site.pk), site.name, "site", parent=parent))
        if tenant_box:
            from tenancy.models import Tenant

            tenant = Tenant.objects.filter(pk=scope.tenant_id).first()
            if tenant is not None and site_ids:
                tenants[tenant.pk] = tenant.name
        for tenant_id, tenant_name in tenants.items():
            nodes.append(Node(nid("tenant", tenant_id), tenant_name, "tenant"))

        # Locations holding drawn devices, with their ancestor locations, nested in their site.
        if draw_hosts and location_ids:
            wanted: dict[int, object] = {}
            for location in Location.objects.filter(pk__in=location_ids):
                for item in [*location.get_ancestors(), location]:
                    wanted[item.pk] = item
            for location in wanted.values():
                if location.parent_id and location.parent_id in wanted:
                    parent = nid("loc", location.parent_id)
                else:
                    parent = nid("site", location.site_id)
                nodes.append(Node(nid("loc", location.pk), location.name, "location", parent=parent))

        return nodes, []
