# SPDX-License-Identifier: AGPL-3.0-or-later
"""netbox-dns collector: a tenant's domains, their records, and the host each name resolves to.

* A **zone** box per DNS zone in the window, titled ``<zone>`` over ``DNS zone``,
  with its name servers as the first entry.
  It sits in the tenant box (a zone belongs to a tenant, not to a site).
* Inside, one **record group** per ``(type, value)``: ``A 172.23.0.254`` over every name that
  resolves there (``@ · auth · erp · …``), so nine names pointing at one edge read as one entry.
  Public records kept in netbox-cloudflare against the same zone join their own groups, marked
  ``Cloudflare`` (and ``proxied``). SOA rows are left out, NS rows folded into one entry;
  TXT-style verification and policy strings are left to the SoT report.
* An arrow from each ``A`` / ``AAAA`` group to the host owning that address (the edge firewall for
  split-horizon names), so a tech can follow ``name → address → box`` and on through the load
  balancer's routing lines.

Window: with a tenant filter, the tenant's zones plus any zone with a record resolving to one of the
window's hosts; otherwise every zone with a record resolving to a host in scope (or every zone in
an unfiltered whole-SoT view). Optional — skipped when netbox-dns is absent.
"""

from __future__ import annotations

import re

from .base import Collector, Edge, Node, Scope, nid, vm_site_id

_ADDRESS_TYPES = frozenset({"A", "AAAA"})
_FOLDED_TYPES = frozenset({"SOA", "NS"})
#: Verification / policy strings (SPF, DKIM, DMARC, site verification): not topology.
_HIDDEN_TYPES = frozenset({"TXT", "SPF", "CAA", "DS", "DNSKEY", "RRSIG", "NSEC", "NSEC3", "NSEC3PARAM"})
_NAMES_PER_LINE = 4


def _natural(text: str) -> list[object]:
    return [int(part) if part.isdigit() else part for part in re.split(r"(\d+)", text)]


class DnsCollector(Collector):
    app_label = "netbox_dns"
    kind = "dnszone"

    def collect(self, scope: Scope) -> tuple[list[Node], list[Edge]]:
        from django.apps import apps
        from ipam.models import IPAddress
        from netbox_dns.models import Record, Zone

        def owner(address: str) -> str | None:
            """The in-scope host (``dev_<pk>`` / ``vm_<pk>``) holding ``address``, if any."""
            for ip in IPAddress.objects.filter(address__net_host=address).prefetch_related(
                "assigned_object"
            ):
                iface = ip.assigned_object
                device = getattr(iface, "device", None)
                vm = getattr(iface, "virtual_machine", None)
                if device is not None and scope.includes_device(device.pk, device.site_id):
                    return nid("dev", device.pk)
                if vm is not None and scope.includes_vm(vm.pk, vm_site_id(vm)):
                    return nid("vm", vm.pk)
            return None

        records = list(Record.objects.select_related("zone").exclude(status="inactive"))
        owners: dict[str, str | None] = {}
        for record in records:
            if record.type in _ADDRESS_TYPES and record.value not in owners:
                owners[record.value] = owner(record.value)

        wanted: set[int] = {r.zone_id for r in records if r.type in _ADDRESS_TYPES and owners.get(r.value)}
        if scope.tenant_id is not None:
            wanted.update(Zone.objects.filter(tenant_id=scope.tenant_id).values_list("pk", flat=True))
        elif scope.mode == "all":
            wanted.update(Zone.objects.values_list("pk", flat=True))

        cloudflare: list[tuple[int, str, str, str, bool]] = []  # zone, name, type, content, proxied
        if apps.is_installed("netbox_cloudflare"):
            from netbox_cloudflare.models import CloudflareRecord

            cloudflare = [
                (r.zone_id, r.name, r.type, r.content, bool(r.proxied))
                for r in CloudflareRecord.objects.filter(zone_id__in=wanted)
            ]
            for _zone, _name, rtype, content, _proxied in cloudflare:
                if rtype in _ADDRESS_TYPES and content not in owners:
                    owners[content] = owner(content)

        nodes: list[Node] = []
        edges: list[Edge] = []
        parent = nid("tenant", scope.tenant_id) if scope.tenant_id is not None else None
        for zone in Zone.objects.filter(pk__in=wanted):
            zone_id = nid("dnszone", zone.pk)
            # Two-line title: Mermaid does not make room for taller subgraph titles, so the name
            # servers go in an entry of their own.
            nodes.append(Node(zone_id, f"{zone.name}\nDNS zone", "dnszone", parent=parent, direction="TB"))
            servers = sorted(
                r.value.rstrip(".") for r in records if r.zone_id == zone.pk and r.type == "NS"
            )
            if servers:
                nodes.append(Node(f"{zone_id}__ns", "NS\n" + "\n".join(servers), "dnsrecord", parent=zone_id))

            groups: dict[tuple[str, str, str], set[str]] = {}  # (source, type, value) -> names
            for record in records:
                if record.zone_id == zone.pk and record.type not in _FOLDED_TYPES | _HIDDEN_TYPES:
                    groups.setdefault(("", record.type, record.value), set()).add(record.name)
            for zone_pk, name, rtype, content, proxied in cloudflare:
                if zone_pk == zone.pk and rtype not in _FOLDED_TYPES | _HIDDEN_TYPES:
                    source = "Cloudflare, proxied" if proxied else "Cloudflare"
                    groups.setdefault((source, rtype, content), set()).add(name)

            for index, ((source, rtype, value), names) in enumerate(
                sorted(groups.items(), key=lambda item: (item[0][0], item[0][1], _natural(item[0][2])))
            ):
                ordered = sorted(names, key=lambda n: (n != "@", _natural(n)))
                rows = [
                    " · ".join(ordered[i : i + _NAMES_PER_LINE])
                    for i in range(0, len(ordered), _NAMES_PER_LINE)
                ]
                shown = value if len(value) <= 48 else value[:45] + "…"
                head = f"{rtype} {shown}" + (f" ({source})" if source else "")
                group_id = f"{zone_id}__r{index}"
                nodes.append(Node(group_id, "\n".join([head, *rows]), "dnsrecord", parent=zone_id))
                target = owners.get(value) if rtype in _ADDRESS_TYPES else None
                if target:
                    edges.append(Edge(group_id, target, ""))  # the arrow reads "resolves to"
        return nodes, edges
