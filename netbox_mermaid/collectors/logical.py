# SPDX-License-Identifier: AGPL-3.0-or-later
"""Logical-topology collector: networks, the hosts on them, and a line for every attachment.

* A **network** node per VLAN (``VLAN <vid> <name>`` over its prefix(es)) and, for a tenant/site
  window, per VLAN-less prefix of that window (a flat site LAN, a point-to-point link). Its label
  also names the **gateway** — ``gw <IP> · <host>`` for the firewall/router SVI in it — so the
  router does not need a line to every network.
* A **host** node per device / VM addressed in a drawn network, labelled with its name over every
  address it has in those networks.
* A **line** from each network to each host addressed in it (``Edge.style="line"``; labelled with
  the address in ``view=all``, where host labels carry only the primary IP).

Address → network matching is **within the same VRF** (overlapping RFC1918 space in different VRFs
never cross-matches), longest prefix first. Networks sit in their site's box (the VLAN's site, else
its group's site; a prefix's scope site). With the gateway in the label, each set of networks that
share hosts is its own connected cluster, which the builder lays out as a grid of clusters.
Drawn by ``view=logical`` and ``view=all``.
"""

from __future__ import annotations

import re

from .base import Collector, Edge, Node, Scope, nid, vm_site_id

#: Device roles whose SVI in a network is that network's gateway.
_GATEWAY_ROLES = frozenset({"firewall", "router"})


def _natural(text: str) -> list[object]:
    return [int(part) if part.isdigit() else part for part in re.split(r"(\d+)", text)]


class LogicalCollector(Collector):
    """Network nodes (VLANs, and a window's VLAN-less prefixes), host nodes, attachment lines."""

    app_label = ""  # core models, always present
    kind = "logical"
    views = frozenset({"logical", "all"})

    def collect(self, scope: Scope) -> tuple[list[Node], list[Edge]]:
        import netaddr
        from django.db.models import Q
        from ipam.models import VLAN, IPAddress, Prefix

        prefixes = list(Prefix.objects.select_related("vlan", "vrf"))
        network_of_prefix: dict[int, str] = {}  # prefix pk -> network node id
        for prefix in prefixes:
            if prefix.vlan_id:
                network_of_prefix[prefix.pk] = nid("vlan", prefix.vlan_id)
            elif scope.tenant_id is not None and prefix.tenant_id == scope.tenant_id:
                network_of_prefix[prefix.pk] = nid("net", prefix.pk)
            elif scope.mode == "site" and _prefix_site(prefix) == scope.site_id:
                network_of_prefix[prefix.pk] = nid("net", prefix.pk)

        # Address → network, longest prefix first, same VRF only.
        indexed = sorted(
            (
                (netaddr.IPNetwork(str(p.prefix)), p.vrf_id, network_of_prefix[p.pk])
                for p in prefixes
                if p.pk in network_of_prefix
            ),
            key=lambda item: item[0].prefixlen,
            reverse=True,
        )
        gateways: dict[str, list[str]] = {}  # network -> ["<ip> · <host>"]
        attached: dict[str, dict[str, str]] = {}  # host id -> {network: ip}
        host_info: dict[str, tuple[str, str, int | None]] = {}  # host id -> (name, kind, site)
        for ip in IPAddress.objects.filter(assigned_object_id__isnull=False).prefetch_related(
            "assigned_object"
        ):
            iface = ip.assigned_object
            device = getattr(iface, "device", None)
            vm = getattr(iface, "virtual_machine", None)
            if device is not None and scope.includes_device(device.pk, device.site_id):
                host_id, kind, site_id = nid("dev", device.pk), "device", device.site_id
                name = device.name or f"device {device.pk}"
                gateway = (getattr(getattr(device, "role", None), "slug", "") or "") in _GATEWAY_ROLES
            elif vm is not None and scope.includes_vm(vm.pk, vm_site_id(vm)):
                host_id, kind, site_id = nid("vm", vm.pk), "vm", vm_site_id(vm)
                name, gateway = vm.name or f"vm {vm.pk}", False
            else:
                continue
            address = netaddr.IPAddress(str(ip.address.ip))
            network = next(
                (net for cidr, vrf, net in indexed if vrf == ip.vrf_id and address in cidr), None
            )
            if network is None:
                continue
            if gateway:
                gateways.setdefault(network, []).append(f"{address} · {name}")
            else:
                attached.setdefault(host_id, {})[network] = str(address)
                host_info[host_id] = (name, kind, site_id)

        # Which networks to draw: every one a drawn host or gateway is on, plus (tenant / site
        # window) that window's VLANs even with nothing on them yet.
        used = set(gateways) | {net for nets in attached.values() for net in nets}
        vlan_ids = {int(net.split("_", 1)[1]) for net in used if net.startswith("vlan_")}
        if scope.tenant_id is not None:
            vlan_ids.update(VLAN.objects.filter(tenant_id=scope.tenant_id).values_list("pk", flat=True))
            vlan_ids = set(
                VLAN.objects.filter(pk__in=vlan_ids)
                .filter(Q(tenant__isnull=True) | Q(tenant_id=scope.tenant_id))
                .values_list("pk", flat=True)
            )
        if scope.mode == "site":
            vlan_ids.update(VLAN.objects.filter(site_id=scope.site_id).values_list("pk", flat=True))

        cidrs: dict[str, list[str]] = {}
        for prefix in prefixes:
            network = network_of_prefix.get(prefix.pk)
            if network:
                cidrs.setdefault(network, []).append(str(prefix.prefix))

        def label(title: str, network: str, with_cidrs: bool = True) -> str:
            lines = [title, *sorted(cidrs.get(network, []) if with_cidrs else [], key=_natural)]
            lines += [f"gw {gw}" for gw in sorted(gateways.get(network, []), key=_natural)]
            return "\n".join(lines)

        nodes: list[Node] = []
        drawn: set[str] = set()
        for vlan in VLAN.objects.filter(pk__in=vlan_ids).select_related("group"):
            network = nid("vlan", vlan.pk)
            site_id = vlan.site_id or _group_site(vlan)
            parent = nid("site", site_id) if site_id else None
            nodes.append(Node(network, label(f"VLAN {vlan.vid} {vlan.name}", network), "vlan", parent=parent))
            drawn.add(network)
        for prefix in prefixes:
            network = nid("net", prefix.pk)
            if network_of_prefix.get(prefix.pk) != network or network not in used:
                continue  # VLAN-less prefixes are drawn only when something is on them
            site_id = _prefix_site(prefix)
            parent = nid("site", site_id) if site_id else None
            title = f"{prefix.prefix} ({prefix.vrf.name})" if prefix.vrf_id else str(prefix.prefix)
            nodes.append(Node(network, label(title, network, with_cidrs=False), "vlan", parent=parent))
            drawn.add(network)

        edges: list[Edge] = []
        for host_id, networks in attached.items():
            networks = {net: ip for net, ip in networks.items() if net in drawn}
            if not networks:
                continue
            name, kind, site_id = host_info[host_id]
            addresses = "\n".join(sorted(networks.values(), key=_natural))
            parent = nid("site", site_id) if site_id else None
            nodes.append(Node(host_id, f"{name}\n{addresses}", kind, parent=parent))
            for network, address in networks.items():
                text = address if scope.view == "all" else ""
                edges.append(Edge(network, host_id, text, style="line"))
        return nodes, edges


def _group_site(vlan: object) -> int | None:
    """The site a VLAN's group is scoped to, if any (``VLANGroup.scope`` is generic)."""
    group = getattr(vlan, "group", None)
    if group is None:
        return None
    return getattr(group, "_site_id", None)


def _prefix_site(prefix: object) -> int | None:
    """The site a prefix is scoped to (NetBox >= 4.2 ``CachedScopeMixin`` ``_site``), if any."""
    return getattr(prefix, "_site_id", None)
