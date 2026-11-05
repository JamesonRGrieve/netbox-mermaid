# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tenant filtering and the physical / logical topology views, against a real NetBox DB (no mocks).

Seeds two tenants on one site: tenant A has a hypervisor (in a cluster), a router cabled to it, a
VLAN with a prefix, and a VM in the cluster with an interface on that VLAN and an address in the
prefix (the router holds the gateway address); tenant B has its own device and VM. Asserts the
tenant window, the ``runs on`` / cable edges of the physical view, the VLAN containers and
membership edges of the logical view, that the views stay separate, that sanitizing the logical
view hides every address and VLAN name, and the REST surface (``tenant`` + ``view`` params).
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

    def test_vm_runs_on_cluster_hypervisor(self):
        mermaid = build_diagram(Scope(view="physical", tenant_id=self.tenant_a.pk)).mermaid
        self.assertIn(f'{nid("vm", self.vm_a.pk)} -->|"runs on"| {nid("dev", self.hv.pk)}', mermaid)

    def test_cable_between_devices(self):
        mermaid = build_diagram(Scope(view="physical")).mermaid
        self.assertIn(f"{nid('dev', self.router.pk)} -->|", mermaid)
        self.assertIn("cable lan0 ↔ eth0", mermaid)

    def test_physical_has_no_vlans(self):
        self.assertNotIn(nid("vlan", self.vlan.pk), build_diagram(Scope(view="physical")).mermaid)


class LogicalViewTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        seed(cls)

    def test_vlan_holds_its_prefix(self):
        mermaid = build_diagram(Scope(view="logical", tenant_id=self.tenant_a.pk)).mermaid
        self.assertIn(f"subgraph {nid('vlan', self.vlan.pk)}", mermaid)
        self.assertIn("VLAN 76 CORP_RDP", mermaid)
        self.assertIn(nid("prefix", self.prefix.pk), mermaid)

    def test_membership_edges(self):
        mermaid = build_diagram(Scope(view="logical")).mermaid
        vlan = nid("vlan", self.vlan.pk)
        self.assertIn(f'{nid("vm", self.vm_a.pk)} -->|"untagged"| {vlan}', mermaid)
        self.assertIn(f'{nid("vm", self.vm_a.pk)} -->|"member"| {vlan}', mermaid)
        self.assertIn(f'{nid("dev", self.router.pk)} -->|"svi"| {vlan}', mermaid)

    def test_services_view_has_no_vlans(self):
        self.assertNotIn(nid("vlan", self.vlan.pk), build_diagram(Scope()).mermaid)

    def test_all_view_has_both(self):
        mermaid = build_diagram(Scope(view="all")).mermaid
        self.assertIn(nid("vlan", self.vlan.pk), mermaid)
        self.assertIn("runs on", mermaid)

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
        self.assertIn("runs on", response.json()["mermaid"])
