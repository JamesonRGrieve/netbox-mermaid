# SPDX-License-Identifier: AGPL-3.0-or-later
"""netbox-data-link collector: the switch-wide L2 control-plane configs — spanning-tree (STP),
LLDP, and DHCP-snooping — nested under their device. Per-interface overrides are omitted from the
diagram for brevity and live in full in the SoT report. Optional — skipped when the plugin is
absent.
"""

from __future__ import annotations

from .base import Collector, Edge, Node, Scope, device_ref, nid

_SELECT = ("device", "device__site")


class DataLinkCollector(Collector):
    app_label = "netbox_data_link"
    kind = "datalink"

    def collect(self, scope: Scope) -> tuple[list[Node], list[Edge]]:
        from netbox_data_link.models import DHCPSnoopingConfig, LLDPConfig, STPConfig

        nodes: list[Node] = []
        for prefix, model, label in (
            ("stp", STPConfig, "STP"),
            ("lldp", LLDPConfig, "LLDP"),
            ("dhcpsnoop", DHCPSnoopingConfig, "DHCP snooping"),
        ):
            for cfg in model.objects.select_related(*_SELECT):
                host_id, site_id = device_ref(cfg.device)
                if not scope.includes_device(cfg.device_id, site_id):
                    continue
                nodes.append(Node(nid(prefix, cfg.pk), label, "datalink", parent=host_id))

        return nodes, []
