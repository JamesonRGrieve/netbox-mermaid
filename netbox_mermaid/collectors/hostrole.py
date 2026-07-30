# SPDX-License-Identifier: AGPL-3.0-or-later
"""netbox-services HostRole collector: the host-level role layer (the device/VM analogue of the
ServiceInstance catalog). Draws each HostRole as a catalog container and every HostRoleAssignment
nested under its target host (a device XOR VM, resolved from the assignment's generic FK) with a
``role`` edge back to the catalog entry. Role-param schema and per-assignment var overrides are
omitted from the diagram for brevity and live in full in the SoT report.

Shares ``netbox_services`` with :class:`~netbox_mermaid.collectors.services.ServicesCollector` but is
a separate collector so the (unrelated) HostRole family is an independent, drop-out concern.
Optional — skipped when the plugin is absent.
"""

from __future__ import annotations

from .base import Collector, Edge, Node, Scope, display, nid


class HostRoleCollector(Collector):
    app_label = "netbox_services"
    kind = "hostrole"

    def collect(self, scope: Scope) -> tuple[list[Node], list[Edge]]:
        from netbox_services.models import HostRole, HostRoleAssignment

        nodes: list[Node] = []
        edges: list[Edge] = []

        if scope.mode == "all":
            for role in HostRole.objects.all():
                nodes.append(
                    Node(nid("hostrole", role.pk), display(role, "display_name", "name"), "hostrole")
                )

        assignments = HostRoleAssignment.objects.select_related(
            "target_object_type", "role"
        ).prefetch_related("target")
        for assign in assignments:
            host_id = self._host_id(assign)
            if host_id is None:
                continue
            if scope.mode != "all" and not self._host_in_scope(scope, assign):
                continue
            nodes.append(
                Node(nid("hostroleassign", assign.pk), display(assign.role, "name"), "hostroleassign", parent=host_id)
            )
            if scope.mode == "all":
                edges.append(
                    Edge(nid("hostroleassign", assign.pk), nid("hostrole", assign.role_id), "role")
                )

        return nodes, edges

    @staticmethod
    def _host_id(assign: object) -> str | None:
        ct = getattr(assign, "target_object_type", None)
        model = ct.model if ct is not None else None
        pk = getattr(assign, "target_object_id", None)
        if model == "device" and pk:
            return nid("dev", pk)
        if model == "virtualmachine" and pk:
            return nid("vm", pk)
        return None

    @staticmethod
    def _host_in_scope(scope: Scope, assign: object) -> bool:
        from .base import vm_site_id

        target = assign.target
        if target is None:
            return False
        ct = getattr(assign, "target_object_type", None)
        model = ct.model if ct is not None else None
        if model == "device":
            return scope.includes_device(target.pk, getattr(target, "site_id", None))
        if model == "virtualmachine":
            return scope.includes_vm(target.pk, vm_site_id(target))
        return False
