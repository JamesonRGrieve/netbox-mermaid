# SPDX-License-Identifier: AGPL-3.0-or-later
"""DNS collector tests against a real NetBox DB (no mocks), skipped when netbox-dns is absent.

Seeds a tenant's zone whose ``www`` and ``@`` A records point at the tenant router's address, plus a
TXT record, and asserts the zone box sits in the tenant box, the A records collapse into one entry
listing both names, the entry arrows to the router, and TXT-style strings stay out.
"""

from unittest import skipUnless

from dcim.models import Interface
from django.apps import apps
from django.test import TestCase
from ipam.models import IPAddress
from tenancy.models import Tenant
from utilities.testing import create_test_device

from netbox_mermaid.builder import build_diagram
from netbox_mermaid.collectors.base import Scope, nid


@skipUnless(apps.is_installed("netbox_dns"), "netbox-dns not installed")
class DnsZoneTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        from netbox_dns.models import NameServer, Record, Zone

        cls.tenant = Tenant.objects.create(name="Tenant Dns", slug="tenant-dns")
        cls.router = create_test_device("mm-dns-router", tenant=cls.tenant)
        port = Interface.objects.create(device=cls.router, name="lan0", type="1000base-t")
        IPAddress.objects.create(address="198.51.100.10/24", assigned_object=port)
        ns = NameServer.objects.create(name="ns1.mm-dns.example")
        cls.zone = Zone.objects.create(
            name="mm-dns.example", soa_mname=ns, soa_rname="hostmaster.mm-dns.example", tenant=cls.tenant
        )
        for name in ("www", "@"):
            Record.objects.create(zone=cls.zone, name=name, type="A", value="198.51.100.10")
        Record.objects.create(zone=cls.zone, name="@", type="TXT", value='"v=spf1 -all"')

    def test_zone_box_in_tenant_box_with_grouped_records_resolving_to_router(self):
        mermaid = build_diagram(Scope(view="services", tenant_id=self.tenant.pk)).mermaid
        zone = nid("dnszone", self.zone.pk)
        self.assertIn(f'subgraph {zone}["mm-dns.example<br/>DNS zone"]', mermaid)
        tenant_at = mermaid.index(f"subgraph {nid('tenant', self.tenant.pk)}")
        self.assertLess(tenant_at, mermaid.index(f"subgraph {zone}"))
        self.assertIn("A 198.51.100.10<br/>@ · www", mermaid)
        self.assertRegex(mermaid, rf"{zone}__r\d+ --> {nid('dev', self.router.pk)}")
        self.assertNotIn("spf1", mermaid)
