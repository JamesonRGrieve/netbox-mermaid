# SPDX-License-Identifier: AGPL-3.0-or-later
"""netbox-services collector: ServiceInstance vertices (nested under their host), the HAMirror
primary↔mirror pairing, and consumer→provider Integration edges. Optional — skipped when the
plugin is absent.
"""

from __future__ import annotations

from .base import Collector, Edge, Node, Scope, nid, vm_site_id


class ServicesCollector(Collector):
    app_label = "netbox_services"
    kind = "service"

    def collect(self, scope: Scope) -> tuple[list[Node], list[Edge]]:
        from netbox_services.models import HAMirror, Integration, ServiceInstance

        nodes: list[Node] = []
        edges: list[Edge] = []
        instances = ServiceInstance.objects.select_related("catalog", "parent_object_type")
        for si in instances:
            host_id = self._host_id(si)
            if scope.mode != "all" and not self._host_in_scope(scope, si):
                continue
            catalog = getattr(si.catalog, "display_name", None) or getattr(si.catalog, "name", "")
            nodes.append(
                Node(
                    nid("svc", si.pk),
                    si.hostname or f"service {si.pk}",
                    "service",
                    parent=host_id,
                    raw_attrs={"catalog": str(catalog)},
                )
            )

        for mirror in HAMirror.objects.all():
            edges.append(
                Edge(nid("svc", mirror.mirror_id), nid("svc", mirror.primary_id), "HA mirror")
            )
        for integ in Integration.objects.all():
            edges.append(
                Edge(
                    nid("svc", integ.consumer_id),
                    nid("svc", integ.provider_id),
                    integ.type or "integration",
                )
            )
        return nodes, edges

    @staticmethod
    def _host_id(si: object) -> str | None:
        ct = getattr(si, "parent_object_type", None)
        model = ct.model if ct is not None else None
        pk = getattr(si, "parent_object_id", None)
        if model == "device" and pk:
            return nid("dev", pk)
        if model == "virtualmachine" and pk:
            return nid("vm", pk)
        return None

    @staticmethod
    def _host_in_scope(scope: Scope, si: object) -> bool:
        host = si.parent  # GFK — resolves to the dcim.Device / virtualization.VirtualMachine
        if host is None:
            return False
        ct = getattr(si, "parent_object_type", None)
        model = ct.model if ct is not None else None
        if model == "device":
            return scope.includes_device(host.pk, getattr(host, "site_id", None))
        if model == "virtualmachine":
            return scope.includes_vm(host.pk, vm_site_id(host))
        return False
