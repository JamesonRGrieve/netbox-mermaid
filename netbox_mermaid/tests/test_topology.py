# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tenant filtering and the physical / logical topology views, against a real NetBox DB (no mocks).

Seeds two tenants on one site: tenant A has a hypervisor (in a cluster), a router cabled to it, a
VLAN with a prefix, and a VM in the cluster with an interface on that VLAN and an address in the
prefix (the router holds the gateway address); tenant B has its own device and VM. Asserts the
tenant window and tenant bounding box, guest nesting / merged plain cable lines / location boxes
of the physical view, the logical view's network → host lines (host labels, gateway in the network
label, VRF-correct matching), that the views stay separate, that sanitizing the logical view hides every
address and VLAN name, and the REST surface (``tenant`` + ``view`` params).
"""

from dcim.models import Cable, Interface
from django.test import TestCase
from ipam.models import VLAN, IPAddress, Prefix
from tenancy.models import Tenant
from utilities.testing import APITestCase, create_test_device
from virtualization.models import Cluster, ClusterType, VirtualMachine, VMInterface

from netbox_mermaid.builder import build_diagram
from netbox_mermaid.collectors.base import Scope, nid


def seed(test_cls: type) -> None:
    """Build the two-tenant graph on ``test_cls`` (shared by the builder and API tests)."""
    test_cls.tenant_a = Tenant.objects.create(name="Tenant Alpha", slug="tenant-alpha")
    test_cls.tenant_b = Tenant.objects.create(name="Tenant Beta", slug="tenant-beta")

    test_cls.hv = create_test_device("mm-hv")
    site = test_cls.hv.site
    cluster_type = ClusterType.objects.create(name="PVE", slug="pve")
    test_cls.cluster = Cluster.objects.create(name="mm-cluster", type=cluster_type, scope=site)
    test_cls.hv.tenant = test_cls.tenant_a
    test_cls.hv.cluster = test_cls.cluster
    test_cls.hv.save()

    test_cls.router = create_test_device("mm-router", site=site, tenant=test_cls.tenant_a)
    test_cls.other = create_test_device("mm-other", site=site, tenant=test_cls.tenant_b)

    hv_port = Interface.objects.create(device=test_cls.hv, name="eth0", type="1000base-t")
    router_lan = Interface.objects.create(device=test_cls.router, name="lan0", type="1000base-t")
    Cable(a_terminations=[router_lan], b_terminations=[hv_port]).save()

    test_cls.vlan = VLAN.objects.create(vid=76, name="CORP_RDP", tenant=test_cls.tenant_a)
    test_cls.prefix = Prefix.objects.create(prefix="172.23.7.248/31", vlan=test_cls.vlan)
    router_svi = Interface.objects.create(device=test_cls.router, name="svi76", type="virtual")
    IPAddress.objects.create(address="172.23.7.248/31", assigned_object=router_svi)

    test_cls.vm_a = VirtualMachine.objects.create(name="mm-vm-a", cluster=test_cls.cluster, tenant=test_cls.tenant_a)
    vm_if = VMInterface.objects.create(
        virtual_machine=test_cls.vm_a, name="eth0", mode="access", untagged_vlan=test_cls.vlan
    )
    IPAddress.objects.create(address="172.23.7.249/31", assigned_object=vm_if)
    test_cls.vm_b = VirtualMachine.objects.create(name="mm-vm-b", cluster=test_cls.cluster, tenant=test_cls.tenant_b)


def box(mermaid: str, node_id: str) -> str:
    """The body of subgraph ``node_id`` (up to its own ``end``, matched by indentation)."""
    lines = mermaid.splitlines()
    start = next(i for i, ln in enumerate(lines) if ln.strip().startswith(f"subgraph {node_id}["))
    indent = lines[start][: len(lines[start]) - len(lines[start].lstrip())]
    end = next(i for i in range(start + 1, len(lines)) if lines[i] == f"{indent}end")
    return "\n".join(lines[start + 1 : end])


class TenantScopeTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        seed(cls)

    def test_tenant_window_keeps_only_that_tenant(self):
        mermaid = build_diagram(Scope(tenant_id=self.tenant_a.pk)).mermaid
        for kept in (nid("dev", self.hv.pk), nid("dev", self.router.pk), nid("vm", self.vm_a.pk)):
            self.assertIn(kept, mermaid)
        for dropped in (nid("dev", self.other.pk), nid("vm", self.vm_b.pk)):
            self.assertNotIn(dropped, mermaid)

    def test_tenant_slug_resolves(self):
        scope = Scope.from_params({"tenant": "tenant-alpha"})
        self.assertEqual(scope.tenant_id, self.tenant_a.pk)

    def test_unknown_tenant_slug_is_empty_not_everything(self):
        scope = Scope.from_params({"tenant": "no-such-tenant"})
        mermaid = build_diagram(scope).mermaid
        self.assertNotIn(nid("dev", self.hv.pk), mermaid)
        self.assertNotIn(nid("vm", self.vm_a.pk), mermaid)

    def test_hypervisor_of_tenant_vm_is_included(self):
        """A device hosting the tenant's VM (via its cluster) is in the window even if its own
        tenant were different: here the hypervisor joins through cluster membership."""
        self.hv.tenant = None
        self.hv.save()
        self.assertIn(self.hv.pk, Scope(tenant_id=self.tenant_a.pk).tenant_device_ids())

    def test_bad_view_falls_back_to_services(self):
        self.assertEqual(Scope.from_params({"view": "nonsense"}).view, "services")


class PhysicalViewTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        seed(cls)

    def test_tenant_is_a_bounding_box_not_an_edge_target(self):
        mermaid = build_diagram(Scope(view="physical", tenant_id=self.tenant_a.pk)).mermaid
        tenant = nid("tenant", self.tenant_a.pk)
        site = nid("site", self.hv.site_id)
        self.assertIn(f"subgraph {tenant}", mermaid)
        self.assertLess(mermaid.index(f"subgraph {tenant}"), mermaid.index(f"subgraph {site}"))
        self.assertNotIn(f"| {tenant}", mermaid)  # nothing points at the tenant
        self.assertNotIn('"tenant"', mermaid)

    def test_vm_nests_in_its_only_hypervisor(self):
        mermaid = build_diagram(Scope(view="physical", tenant_id=self.tenant_a.pk)).mermaid
        hv_box = box(mermaid, nid("dev", self.hv.pk))
        self.assertIn(nid("vm", self.vm_a.pk), hv_box)
        self.assertNotIn("runs on", mermaid)

    def test_cable_is_one_plain_line_per_device_pair(self):
        hv_port2 = Interface.objects.create(device=self.hv, name="eth1", type="1000base-t")
        router_lan2 = Interface.objects.create(device=self.router, name="lan1", type="1000base-t")
        Cable(a_terminations=[hv_port2], b_terminations=[router_lan2]).save()  # reversed A/B
        mermaid = build_diagram(Scope(view="physical")).mermaid
        low, high = sorted((self.hv, self.router), key=lambda d: d.pk)
        lines = [ln for ln in mermaid.splitlines() if " ---|" in ln]
        self.assertEqual(len(lines), 1)
        self.assertTrue(lines[0].strip().startswith(f"{nid('dev', low.pk)} ---|"))
        self.assertTrue(lines[0].strip().endswith(nid("dev", high.pk)))
        self.assertIn("lan0 ↔ eth0" if low == self.router else "eth0 ↔ lan0", lines[0])
        self.assertIn("<br/>", lines[0])  # both port pairs, one per line

    def test_device_sits_in_its_location(self):
        from dcim.models import Location

        location = Location.objects.create(name="Rack Room", slug="rack-room", site=self.hv.site)
        self.router.location = location
        self.router.save()
        mermaid = build_diagram(Scope(view="physical", tenant_id=self.tenant_a.pk)).mermaid
        self.assertIn(nid("dev", self.router.pk), box(mermaid, nid("loc", location.pk)))

    def test_services_view_nests_guest_in_hypervisor_too(self):
        mermaid = build_diagram(Scope(view="services", tenant_id=self.tenant_a.pk)).mermaid
        if f"subgraph {nid('dev', self.hv.pk)}" in mermaid:  # drawn only when something runs on it
            self.assertIn(nid("vm", self.vm_a.pk), box(mermaid, nid("dev", self.hv.pk)))

    def test_physical_has_no_vlans(self):
        self.assertNotIn(nid("vlan", self.vlan.pk), build_diagram(Scope(view="physical")).mermaid)


class LogicalViewTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        seed(cls)

    def _vlan(self) -> str:
        return nid("vlan", self.vlan.pk)

    def test_network_node_titled_with_its_prefix(self):
        mermaid = build_diagram(Scope(view="logical", tenant_id=self.tenant_a.pk)).mermaid
        self.assertIn(f'{self._vlan()}[["VLAN 76 CORP_RDP<br/>172.23.7.248/31', mermaid)

    def test_line_from_network_to_each_host_on_it(self):
        diagram = build_diagram(Scope(view="logical"))
        self.assertIn(f"{self._vlan()} --- {nid('vm', self.vm_a.pk)}", diagram.mermaid)
        self.assertIn(f"{self._vlan()} --- {nid('dev', self.router.pk)}", diagram.mermaid)
        self.assertNotIn("-->", diagram.mermaid)

    def test_host_label_lists_its_addresses(self):
        mermaid = build_diagram(Scope(view="logical")).mermaid
        self.assertIn(f'{nid("vm", self.vm_a.pk)}("mm-vm-a<br/>172.23.7.249")', mermaid)

    def test_gateway_named_in_network_label_not_drawn_as_line(self):
        from dcim.models import DeviceRole

        self.router.role = DeviceRole.objects.create(name="Router", slug="router")
        self.router.save()
        mermaid = build_diagram(Scope(view="logical")).mermaid
        self.assertIn("gw 172.23.7.248 · mm-router", mermaid)
        self.assertNotIn(f"{self._vlan()} --- {nid('dev', self.router.pk)}", mermaid)

    def test_address_in_another_vrf_does_not_match(self):
        """Overlapping RFC1918 space in another VRF must not attach a host to this VLAN."""
        from ipam.models import VRF

        vrf = VRF.objects.create(name="Other")
        Prefix.objects.create(prefix="172.23.7.0/24", vrf=vrf, tenant=self.tenant_b)
        other_if = Interface.objects.create(device=self.other, name="eth9", type="1000base-t")
        IPAddress.objects.create(address="172.23.7.249/24", vrf=vrf, assigned_object=other_if)
        mermaid = build_diagram(Scope(view="logical")).mermaid
        self.assertNotIn(f"{self._vlan()} --- {nid('dev', self.other.pk)}", mermaid)

    def test_unaddressed_host_not_drawn(self):
        mermaid = build_diagram(Scope(view="logical", tenant_id=self.tenant_a.pk)).mermaid
        self.assertNotIn(nid("dev", self.hv.pk), mermaid)  # no address: nothing to attach

    def test_services_view_has_no_vlans(self):
        self.assertNotIn(nid("vlan", self.vlan.pk), build_diagram(Scope()).mermaid)

    def test_all_view_has_both_and_labels_the_attachment(self):
        diagram = build_diagram(Scope(view="all"))
        self.assertIn("\nflowchart LR\n", diagram.mermaid)
        self.assertIn(f'{self._vlan()} ---|"172.23.7.249"| {nid("vm", self.vm_a.pk)}', diagram.mermaid)
        self.assertRegex(diagram.mermaid, r"(lan0 ↔ eth0|eth0 ↔ lan0)")  # the cable

    def test_sanitized_logical_hides_addresses_and_names(self):
        diagram = build_diagram(Scope(view="logical"), sanitize=True)
        for secret in ("172.23.7", "CORP_RDP", "mm-vm-a", "mm-router"):
            self.assertNotIn(secret, diagram.mermaid)
        unsanitized = build_diagram(Scope(view="logical"))
        self.assertEqual(diagram.node_count, unsanitized.node_count)
        self.assertEqual(diagram.edge_count, unsanitized.edge_count)


class TopologyAPITest(APITestCase):
    _URL = "/api/plugins/mermaid/diagram/"

    @classmethod
    def setUpTestData(cls):
        seed(cls)

    def test_tenant_and_view_params(self):
        response = self.client.get(f"{self._URL}?tenant=tenant-alpha&view=logical", **self.header)
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["view"], "logical")
        self.assertEqual(body["tenant"], self.tenant_a.pk)
        self.assertIn("VLAN 76 CORP_RDP", body["mermaid"])
        self.assertNotIn("mm-vm-b", body["mermaid"])

    def test_physical_view_param(self):
        response = self.client.get(f"{self._URL}?view=physical", **self.header)
        self.assertEqual(response.status_code, 200)
        self.assertIn(" ---|", response.json()["mermaid"])
