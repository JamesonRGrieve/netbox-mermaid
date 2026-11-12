# SPDX-License-Identifier: AGPL-3.0-or-later
"""Collector-registry + render-safety tests.

Two concerns, both DB-free (pure):

* **Registry coverage** — every collector is wired in and de-duplicated, and running the full
  registry on an install where the sibling plugins are absent is a graceful no-op (the guarded
  imports skip, never raise).
* **Kind-id uniqueness** — every diagram ``kind`` that a collector can emit must have a *distinct*
  sanitizer id abbreviation. This is load-bearing: the sanitizer numbers synthetic ids per kind, so
  two kinds sharing an abbreviation (e.g. ``hostrole`` / ``hostroleassign`` both defaulting to
  ``HOS``) would mint colliding ids and silently merge unrelated nodes in the public-safe diagram.
"""

from django.test import SimpleTestCase

from netbox_mermaid.builder import _KIND_COLORS
from netbox_mermaid.collectors.base import Edge, Node, Scope
from netbox_mermaid.collectors.registry import COLLECTORS, anchor_to, collect_all, hosts_in_use
from netbox_mermaid.sanitizer import _ID_ABBR


class RegistryTest(SimpleTestCase):
    def test_expected_collectors_registered(self):
        classnames = {type(c).__name__ for c in COLLECTORS}
        for expected in (
            "CoreCollector",
            "ServicesCollector",
            "HostRoleCollector",
            "AiCollector",
            "DnsCollector",
            "CloudflareCollector",
            "LbAclCollector",
            "PfCollector",
            "DhcpCollector",
            "DataLinkCollector",
            "WireGuardCollector",
            "ReticulumCollector",
            "MeshCoreCollector",
            "ZfsCollector",
            "GuestsCollector",
        ):
            self.assertIn(expected, classnames)

    def test_collect_all_is_graceful_without_plugins(self):
        # Guarded imports mean an absent plugin contributes nothing rather than raising.
        nodes, edges = collect_all(Scope())
        self.assertIsInstance(nodes, list)
        self.assertIsInstance(edges, list)


class KindAbbrUniquenessTest(SimpleTestCase):
    def test_id_abbreviations_are_unique(self):
        abbrs = list(_ID_ABBR.values())
        dupes = {a for a in abbrs if abbrs.count(a) > 1}
        self.assertEqual(dupes, set(), f"colliding sanitizer id abbreviations: {dupes}")

    def test_every_coloured_kind_has_a_distinct_abbr(self):
        # A kind that has a colour is a kind a collector emits; it must map to a unique synthetic id
        # prefix so the sanitizer can't merge two kinds under one abbreviation.
        for kind in _KIND_COLORS:
            self.assertIn(kind, _ID_ABBR, f"kind {kind!r} missing a sanitizer id abbreviation")


class TenantAnchoringTest(SimpleTestCase):
    """Pure checks of the registry's tenant-window pruning (no DB rows needed)."""

    def test_global_objects_kept_only_when_tied_to_the_window(self):
        anchors = [Node("site_1", "S", "site"), Node("vm_1", "app", "vm", parent="site_1")]
        layered = [
            Node("svc_1", "web", "service", parent="vm_1"),  # nests in the window
            Node("aicatalog_1", "Model A", "aicatalog"),  # one hop from svc_1
            Node("aivariant_1", "A q4", "aivariant", parent="aicatalog_1"),
            Node("aicatalog_2", "Model B", "aicatalog"),  # nothing in the window uses it
        ]
        edges = [Edge("svc_1", "aivariant_1", "serves")]
        kept = {n.id for n in anchor_to(anchors, layered, edges)}
        self.assertEqual(kept, {"svc_1", "aivariant_1", "aicatalog_1"})

    def test_services_view_drops_idle_hosts(self):
        anchors = [
            Node("site_1", "S", "site"),
            Node("loc_1", "Rack", "location", parent="site_1"),
            Node("dev_1", "switch", "device", parent="loc_1"),
            Node("vm_1", "app", "vm", parent="site_1"),
        ]
        kept = {n.id for n in hosts_in_use(anchors, [Node("svc_1", "web", "service", parent="vm_1")], [])}
        self.assertEqual(kept, {"site_1", "vm_1"})

    def test_services_view_keeps_edge_targets_and_everything_without_service_data(self):
        anchors = [
            Node("site_1", "S", "site"),
            Node("dev_1", "firewall", "device", parent="site_1"),
            Node("dev_2", "switch", "device", parent="site_1"),
        ]
        zone = [Node("dnszone_1", "z", "dnszone"), Node("dnszone_1__r0", "A", "dnsrecord", parent="dnszone_1")]
        kept = {n.id for n in hosts_in_use(anchors, zone, [Edge("dnszone_1__r0", "dev_1", "")])}
        self.assertEqual(kept, {"site_1", "dev_1"})
        self.assertEqual(hosts_in_use(anchors, [], []), anchors)
