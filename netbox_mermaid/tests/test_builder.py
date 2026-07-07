# SPDX-License-Identifier: AGPL-3.0-or-later
"""Builder tests against a real NetBox DB (no mocks).

Builds a small real graph (Site + Device + VM) via NetBox's test helpers, runs the full collect →
render pipeline, and asserts the emitted Mermaid header, node ids/labels, subgraph nesting, and
label escaping. Plugin-specific assertions are guarded behind ``apps.is_installed(...)``.
"""

from django.apps import apps
from django.test import TestCase
from utilities.testing import create_test_device, create_test_virtualmachine

from netbox_mermaid.builder import build_diagram, escape_label, render
from netbox_mermaid.collectors.base import Edge, Node, Scope, nid


class LabelEscapingTest(TestCase):
    """Pure render-layer checks: the header, shapes, and Mermaid-special-char escaping."""

    def test_header(self):
        diagram = render([Node("dev_1", "host", "device")], [])
        self.assertTrue(diagram.mermaid.startswith("flowchart TD"))

    def test_special_chars_escaped(self):
        raw = 'A "quoted" #hash <b> |pipe {brace}'
        diagram = render([Node("dev_1", raw, "device")], [])
        # The dangerous raw characters must not survive verbatim inside the label.
        self.assertNotIn('"quoted"', diagram.mermaid)
        self.assertIn("#34;", diagram.mermaid)  # quote
        self.assertIn("#35;", diagram.mermaid)  # hash
        self.assertIn("#60;", diagram.mermaid)  # <
        self.assertIn("#124;", diagram.mermaid)  # pipe
        self.assertIn("#123;", diagram.mermaid)  # {

    def test_escape_label_quotes_result(self):
        self.assertEqual(escape_label("plain"), '"plain"')

    def test_edge_and_counts(self):
        nodes = [Node("dev_1", "h1", "device"), Node("db_2", "d1", "database", parent="dev_1")]
        edges = [Edge("db_2", "dev_1", "runs on"), Edge("db_2", "missing", "dropped")]
        diagram = render(nodes, edges)
        self.assertEqual(diagram.node_count, 2)
        self.assertEqual(diagram.edge_count, 1)  # the edge to a missing endpoint is dropped
        self.assertIn("subgraph dev_1", diagram.mermaid)  # a node with children becomes a subgraph
        self.assertIn("-->|", diagram.mermaid)


class BuilderGraphTest(TestCase):
    """End-to-end collect → render over real core objects."""

    @classmethod
    def setUpTestData(cls):
        cls.device = create_test_device("mm-host")
        cls.site = cls.device.site
        cls.vm = create_test_virtualmachine("mm-vm")

    def test_whole_sot_contains_core_nodes(self):
        diagram = build_diagram(Scope())
        self.assertTrue(diagram.mermaid.startswith("flowchart TD"))
        self.assertIn(nid("dev", self.device.pk), diagram.mermaid)
        self.assertIn(nid("vm", self.vm.pk), diagram.mermaid)
        self.assertIn("mm-host", diagram.mermaid)
        self.assertGreater(diagram.node_count, 0)

    def test_device_nested_under_site(self):
        if not self.site:
            self.skipTest("test device has no site")
        diagram = build_diagram(Scope())
        self.assertIn(f"subgraph {nid('site', self.site.pk)}", diagram.mermaid)

    def test_services_optional(self):
        # Plugin-specific: only asserts the services layer when the plugin is actually installed.
        diagram = build_diagram(Scope())
        if apps.is_installed("netbox_services"):
            from netbox_services.models import ServiceInstance

            if ServiceInstance.objects.exists():
                self.assertIn("svc_", diagram.mermaid)
        # Absent plugin: the diagram still builds over core, which the whole-SoT test covers.
        self.assertTrue(diagram.mermaid)
