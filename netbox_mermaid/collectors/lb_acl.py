# SPDX-License-Identifier: AGPL-3.0-or-later
"""netbox-load-balancing(-acl) collector: the request path through each load balancer.

* One **HAProxy** node per device running load-balancer services (``LBServiceAssignment`` to a
  device), inside that device's box, listing each service's listeners (``https :443``).
* One **line per backend reached**, from that node to the guest (or device) holding the pool
  member's address, labelled with every hostname routed there
  (``host_matches`` routing rules; ``(default)`` for a default backend) and the backend port.

So ``name → edge firewall → HAProxy → guest`` reads straight off the diagram. ACL / certificate
rows are not drawn (the SoT report has them). Window: a node is drawn when its device is in scope;
a line when its target is too, which anchors it to a tenant's hosts. Optional — skipped when the
plugin is absent (it depends on netbox-load-balancing, whose models it reads).
"""

from __future__ import annotations

import re

from .base import Collector, Edge, Node, Scope, nid, vm_site_id


def _natural(text: str) -> list[object]:
    return [int(part) if part.isdigit() else part for part in re.split(r"(\d+)", text)]


class LbAclCollector(Collector):
    app_label = "netbox_load_balancing_acl"
    kind = "lbacl"

    def collect(self, scope: Scope) -> tuple[list[Node], list[Edge]]:
        from django.contrib.contenttypes.models import ContentType
        from netbox_load_balancing.models import (
            LBServiceAssignment,
            Listener,
            MemberAssignment,
            Pool,
        )
        from netbox_load_balancing_acl.models import LBRoutingRule

        from dcim.models import Device

        # Which device runs each LB service.
        device_ct = ContentType.objects.get_for_model(Device)
        service_device: dict[int, int] = {}
        for assignment in LBServiceAssignment.objects.filter(assigned_object_type=device_ct):
            service_device[assignment.service_id] = assignment.assigned_object_id
        devices = {
            d.pk: d for d in Device.objects.filter(pk__in=set(service_device.values()))
            if scope.includes_device(d.pk, d.site_id)
        }

        listeners: dict[int, list[str]] = {}  # device pk -> ["svc: name proto :port"]
        listener_device: dict[int, int] = {}
        for listener in Listener.objects.select_related("service").order_by("service__name", "port"):
            device = service_device.get(listener.service_id)
            if device not in devices:
                continue
            listener_device[listener.pk] = device
            listeners.setdefault(device, []).append(f"{listener.service.name}: {listener.name} :{listener.port}")

        # Pool -> (target node id, port) for each member address held by an in-scope host.
        pool_ct = ContentType.objects.get_for_model(Pool)
        pools = {p.pk: p for p in Pool.objects.all()}
        members: dict[int, list[str]] = {}
        for assignment in MemberAssignment.objects.filter(assigned_object_type=pool_ct).select_related(
            "member__ip_address"
        ):
            if assignment.disabled or assignment.member.ip_address is None:
                continue
            iface = assignment.member.ip_address.assigned_object
            device = getattr(iface, "device", None)
            vm = getattr(iface, "virtual_machine", None)
            if device is not None and scope.includes_device(device.pk, device.site_id):
                host = ("dcim", "device", device.pk)
            elif vm is not None and scope.includes_vm(vm.pk, vm_site_id(vm)):
                host = ("virtualization", "virtualmachine", vm.pk)
            else:
                continue
            members.setdefault(assignment.assigned_object_id, []).append(host)

        def target(host: tuple[str, str, int]) -> str:
            # The guest / device holding the member address: several instances on one host often
            # share a hostname (app, its database, its cache), so naming one would be a guess.
            _app, model, pk = host
            return nid("dev" if model == "device" else "vm", pk)

        routes: dict[tuple[int, int], set[str]] = {}  # (device, pool) -> hostnames
        for rule in LBRoutingRule.objects.filter(listener_id__in=listener_device, target_pool__isnull=False):
            if rule.match_type == "host_matches" and rule.pattern and not rule.negate:
                name = rule.pattern
            elif rule.action_type == "default_backend":
                name = "(default)"
            else:
                continue
            routes.setdefault((listener_device[rule.listener_id], rule.target_pool_id), set()).add(name)

        nodes: list[Node] = []
        edges: list[Edge] = []
        lines: dict[tuple[str, str], tuple[set[str], set[int]]] = {}
        for (device, pool_id), hostnames in routes.items():
            pool = pools.get(pool_id)
            for host in members.get(pool_id, []):
                key = (nid("lb", device), target(host))
                names, ports = lines.setdefault(key, (set(), set()))
                names.update(hostnames)
                if pool is not None and pool.member_port:
                    ports.add(pool.member_port)
        for device in sorted({d for d, _ in routes} | set(listeners)):
            if device not in devices:
                continue
            label = "\n".join(["HAProxy", *listeners.get(device, [])])
            nodes.append(Node(nid("lb", device), label, "lblistener", parent=nid("dev", device)))
        for (src, dst), (names, ports) in lines.items():
            ordered = sorted(names, key=lambda n: (n == "(default)", _natural(n)))
            port = " · ".join(f":{p}" for p in sorted(ports))
            edges.append(Edge(src, dst, "\n".join(ordered + ([f"→ {port}"] if port else []))))
        return nodes, edges
