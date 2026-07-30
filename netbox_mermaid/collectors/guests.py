# SPDX-License-Identifier: AGPL-3.0-or-later
"""netbox-guests collector: the Proxmox guest extras — pass-through GuestDevices (GPU/USB/PCI) and
GuestMounts — nested under their virtual machine. Optional — skipped when the plugin is absent.
"""

from __future__ import annotations

from .base import Collector, Edge, Node, Scope, host_in_scope, host_ref, nid

_SELECT = (
    "virtual_machine",
    "virtual_machine__site",
    "virtual_machine__cluster",
    "virtual_machine__cluster__site",
)


class GuestsCollector(Collector):
    app_label = "netbox_guests"
    kind = "guestdev"

    def collect(self, scope: Scope) -> tuple[list[Node], list[Edge]]:
        from netbox_guests.models import GuestDevice, GuestMount

        nodes: list[Node] = []

        for dev in GuestDevice.objects.select_related(*_SELECT):
            if not host_in_scope(scope, dev):
                continue
            host_id, _ = host_ref(dev)
            label = f"{dev.kind}/{dev.selector}"
            nodes.append(Node(nid("guestdev", dev.pk), label, "guestdev", parent=host_id))

        for mount in GuestMount.objects.select_related(*_SELECT):
            if not host_in_scope(scope, mount):
                continue
            host_id, _ = host_ref(mount)
            label = f"mp{mount.mp} → {mount.path}"
            nodes.append(Node(nid("guestmount", mount.pk), label, "guestmount", parent=host_id))

        return nodes, []
