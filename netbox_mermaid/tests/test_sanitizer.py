# SPDX-License-Identifier: AGPL-3.0-or-later
"""Sanitizer threat-model tests: the redacted output must leak none of the seeded hostnames, IPs,
e-mails, or secret refs; the same real value must map to the same generic label (determinism); and
node/edge COUNTS must be preserved (structure intact). Pure — no DB needed."""

from django.test import SimpleTestCase

from netbox_mermaid.collectors.base import Edge, Node
from netbox_mermaid.sanitizer import Sanitizer

# A seeded graph carrying every sensitive-data category the sanitizer must scrub.
_HOSTNAME = "host-prod-01.example.internal"
_IP = "10.0.0.5"
_EMAIL = "admin@corp.example.com"
_SECRET = "secret/kv/data/db-prod"
_TENANT = "Acme Customer Corp"

_NODES = [
    Node("dev_5", _HOSTNAME, "device"),
    Node("db_9", f"{_IP} mariadb", "dbserver", parent="dev_5"),
    Node("svc_3", _SECRET, "service", parent="dev_5"),
    Node("ten_7", _TENANT, "tenant"),
]
_EDGES = [
    Edge("db_9", "dev_5", f"reads from {_HOSTNAME}"),
    Edge("svc_3", "db_9", f"notify {_EMAIL}"),
]

_LEAKS = [
    _HOSTNAME,
    "host-prod-01",
    _IP,
    _EMAIL,
    "admin@corp",
    _SECRET,
    "secret/kv",
    _TENANT,
    "example.internal",
]


class SanitizerLeakTest(SimpleTestCase):
    def setUp(self):
        self.nodes, self.edges = Sanitizer().sanitize(list(_NODES), list(_EDGES))
        self.blob = "\n".join(
            [n.id for n in self.nodes]
            + [n.label for n in self.nodes]
            + [e.label for e in self.edges]
            + [e.src for e in self.edges]
            + [e.dst for e in self.edges]
        )

    def test_no_identifying_data_survives(self):
        for leak in _LEAKS:
            self.assertNotIn(leak, self.blob, f"sanitized output leaked {leak!r}")

    def test_real_pks_replaced_with_synthetic_ids(self):
        for node in self.nodes:
            self.assertNotIn("_5", node.id)
            self.assertNotIn("_9", node.id)

    def test_counts_preserved(self):
        self.assertEqual(len(self.nodes), len(_NODES))
        self.assertEqual(len(self.edges), len(_EDGES))

    def test_email_placeholder_present(self):
        # The e-mail lives in an edge label (edge labels keep their verb, only sensitive spans are
        # scrubbed) so it must surface as the «email» placeholder.
        self.assertIn("«email»", self.blob)

    def test_same_value_maps_to_same_label(self):
        # The hostname appears in both the device node label and an edge label; both must resolve to
        # the SAME generic token.
        device = next(n for n in self.nodes if n.kind == "device")
        host_edge = next(e for e in self.edges if e.dst == device.id)
        self.assertIn(device.label, host_edge.label)
        self.assertNotIn(_HOSTNAME, host_edge.label)

    def test_tenant_uses_letter_suffix(self):
        tenant = next(n for n in self.nodes if n.kind == "tenant")
        self.assertEqual(tenant.label, "Tenant A")

    def test_deterministic(self):
        n1, e1 = Sanitizer().sanitize(list(_NODES), list(_EDGES))
        n2, e2 = Sanitizer().sanitize(list(_NODES), list(_EDGES))
        self.assertEqual(
            [(n.id, n.label, n.parent) for n in n1], [(n.id, n.label, n.parent) for n in n2]
        )
        self.assertEqual(
            [(e.src, e.dst, e.label) for e in e1], [(e.src, e.dst, e.label) for e in e2]
        )

    def test_parent_remapped(self):
        # db_9 nested under dev_5 → the child's parent must point at the device's synthetic id.
        device = next(n for n in self.nodes if n.kind == "device")
        dbserver = next(n for n in self.nodes if n.kind == "dbserver")
        self.assertEqual(dbserver.parent, device.id)
