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
from netbox_mermaid.collectors.base import Scope
from netbox_mermaid.collectors.registry import COLLECTORS, collect_all
from netbox_mermaid.sanitizer import _ID_ABBR


class RegistryTest(SimpleTestCase):
    def test_expected_collectors_registered(self):
        classnames = {type(c).__name__ for c in COLLECTORS}
        for expected in (
            "CoreCollector",
            "ServicesCollector",
            "HostRoleCollector",
            "AiCollector",
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
