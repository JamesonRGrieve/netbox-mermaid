# SPDX-License-Identifier: AGPL-3.0-or-later
"""Builder tests against a real NetBox DB (no mocks).

Builds a small real graph (Site + Device + VM) via NetBox's test helpers, runs the full collect →
render pipeline, and asserts the emitted Mermaid header, node ids/labels, subgraph nesting, and
label escaping. Plugin-specific assertions are guarded behind ``apps.is_installed(...)``.
"""

from django.apps import apps
from django.test import TestCase
from utilities.testing import create_test_device, create_test_virtualmachine

from netbox_mermaid.builder import MERMAID_INIT, build_diagram, escape_label, render
from netbox_mermaid.collectors.base import Edge, Node, Scope, nid


class LabelEscapingTest(TestCase):
    """Pure render-layer checks: the header, shapes, and Mermaid-special-char escaping."""

    def test_header(self):
        lines = render([Node("dev_1", "host", "device")], []).mermaid.splitlines()
        self.assertEqual(lines[0], MERMAID_INIT)  # straight connectors, compact spacing
        self.assertEqual(lines[1], "flowchart TD")

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

    def test_line_edge_has_no_arrowhead(self):
        nodes = [Node("dev_1", "a", "device"), Node("dev_2", "b", "device")]
        diagram = render(nodes, [Edge("dev_1", "dev_2", "eth0 ↔ 1/1", style="line")])
        self.assertIn('dev_1 ---|"eth0 ↔ 1/1"| dev_2', diagram.mermaid)
        self.assertNotIn("-->", diagram.mermaid)

    def test_many_free_children_form_a_grid(self):
        """Nine edge-free guests in one host become three invisible LR columns of three, read in
        natural order (``vm 2`` before ``vm 10``); the column wrappers are not counted as nodes."""
        nodes = [Node("dev_1", "host", "device")] + [
            Node(f"vm_{i}", f"vm {i}", "vm", parent="dev_1") for i in (1, 2, 3, 4, 5, 6, 7, 8, 10)
        ]
        diagram = render(nodes, [])
        self.assertEqual(diagram.node_count, 10)
        self.assertEqual(diagram.mermaid.count("subgraph dev_1__col"), 3)
        self.assertIn("style dev_1__col0 fill:none,stroke:none;", diagram.mermaid)
        col0 = diagram.mermaid.split("subgraph dev_1__col0")[1].split("end")[0]
        self.assertIn("direction LR", col0)
        self.assertLess(col0.index("vm_1"), col0.index("vm_2"))
        self.assertIn("vm_3", col0)
        self.assertNotIn("~~~", diagram.mermaid)  # no layout links: they crash Mermaid's dagre

    def test_few_or_wired_children_are_not_gridded(self):
        nodes = [Node("dev_1", "host", "device")] + [
            Node(f"vm_{i}", f"vm {i}", "vm", parent="dev_1") for i in range(9)
        ] + [Node("dev_2", "peer", "device")]
        edges = [Edge(f"vm_{i}", "dev_2", "x") for i in range(4)]  # 5 free left: one row is fine
        self.assertNotIn("__col", render(nodes, edges).mermaid)

    def test_sibling_subgraphs_emitted_in_reverse(self):
        """Mermaid lays sibling subgraphs out in reverse definition order; emitting them reversed
        makes them read in natural order on screen."""
        nodes = [Node("site_1", "S", "site")]
        for vid in (4, 60, 10):
            nodes += [
                Node(f"vlan_{vid}", f"VLAN {vid}", "vlan", parent="site_1"),
                Node(f"m_{vid}", "h", "device", parent=f"vlan_{vid}"),
            ]
        mermaid = render(nodes, []).mermaid
        order = [mermaid.index(f"subgraph vlan_{vid}") for vid in (60, 10, 4)]
        self.assertEqual(order, sorted(order))


class ComponentGridTest(TestCase):
    """Clusters of siblings joined only to each other are gridded as units, crossing-reduced."""

    def _nodes(self) -> tuple[list[Node], list[Edge]]:
        nodes = [Node("site_1", "S", "site")]
        edges = []
        for i in range(1, 9):
            nodes += [
                Node(f"vlan_{i}", f"VLAN {i}", "vlan", parent="site_1"),
                Node(f"vm_{i}", f"guest {i}", "vm", parent="site_1"),
            ]
            edges.append(Edge(f"vlan_{i}", f"vm_{i}", "", style="line"))
        # One host on two networks joins VLAN 1 and VLAN 2 into a single unit.
        nodes.append(Node("dev_9", "nas", "device", parent="site_1"))
        edges += [Edge("vlan_1", "dev_9", "", style="line"), Edge("vlan_2", "dev_9", "", style="line")]
        return nodes, edges

    def test_units_stay_together_in_one_column(self):
        mermaid = render(*self._nodes()).mermaid
        self.assertIn("subgraph site_1__col", mermaid)
        self.assertIn("direction TB", mermaid.split("subgraph site_1[")[1].splitlines()[1])
        for i in range(1, 9):
            col = next(c for c in mermaid.split("subgraph site_1__col")[1:] if f"vlan_{i}[" in c.split("end")[0])
            self.assertIn(f"vm_{i}(", col.split("end")[0])
        shared = next(c for c in mermaid.split("subgraph site_1__col")[1:] if "vlan_1[" in c.split("end")[0])
        self.assertIn("vlan_2[", shared.split("end")[0])
        self.assertIn("dev_9[", shared.split("end")[0])

    def test_sources_emitted_before_their_targets(self):
        mermaid = render(*self._nodes()).mermaid
        self.assertLess(mermaid.index("vlan_1["), mermaid.index("dev_9["))
        self.assertLess(mermaid.index("vlan_2["), mermaid.index("dev_9["))

    def test_lr_root_uses_tb_rows(self):
        nodes = [Node("dev_1", "host", "device")] + [
            Node(f"vm_{i}", f"vm {i}", "vm", parent="dev_1") for i in range(9)
        ]
        mermaid = render(nodes, [], "LR").mermaid
        self.assertEqual(mermaid.splitlines()[1], "flowchart LR")
        col0 = mermaid.split("subgraph dev_1__col0")[1].split("end")[0]
        self.assertIn("direction TB", col0)


class BuilderGraphTest(TestCase):
    """End-to-end collect → render over real core objects."""

    @classmethod
    def setUpTestData(cls):
        cls.device = create_test_device("mm-host")
        cls.site = cls.device.site
        cls.vm = create_test_virtualmachine("mm-vm")

    def test_whole_sot_contains_core_nodes(self):
        diagram = build_diagram(Scope())
        self.assertIn("\nflowchart TD\n", diagram.mermaid)
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


class ClusterScopedVMTest(TestCase):
    """Regression: NetBox >= 4.2 has no ``Cluster.site`` (it is the cached ``_site`` of the generic
    ``scope``). A ``cluster__site`` lookup raised FieldError, safe_collect swallowed it, and the
    core collector emitted no site/device/VM at all in prod."""

    @classmethod
    def setUpTestData(cls):
        from virtualization.models import Cluster, ClusterType, VirtualMachine

        device = create_test_device("mm-cl-host")
        cls.site = device.site
        cluster = Cluster.objects.create(
            name="mm-cl", type=ClusterType.objects.create(name="mm-ct", slug="mm-ct"), scope=cls.site
        )
        cls.vm = VirtualMachine.objects.create(name="mm-cl-vm", cluster=cluster)

    def test_core_collector_does_not_fail(self):
        from netbox_mermaid.collectors.core import CoreCollector

        nodes, _edges = CoreCollector().collect(Scope())  # collect(), not safe_collect(): must not raise
        self.assertIn(nid("vm", self.vm.pk), {n.id for n in nodes})

    def test_cluster_vm_nested_under_cluster_site(self):
        diagram = build_diagram(Scope(mode="site", site_id=self.site.pk))
        self.assertIn(f"subgraph {nid('site', self.site.pk)}", diagram.mermaid)
        self.assertIn(nid("vm", self.vm.pk), diagram.mermaid)
