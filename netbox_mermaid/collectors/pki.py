# SPDX-License-Identifier: AGPL-3.0-or-later
"""netbox-pki collector: Certificate Authorities (containers) with their ACME accounts and issued
Certificates nested beneath, plus each certificate's ``secures`` edge to the ServiceInstance it
protects. PKI is not host-anchored, so it populates only in whole-SoT (``all``) scope. Optional —
skipped when the plugin is absent.
"""

from __future__ import annotations

from .base import Collector, Edge, Node, Scope, nid


class PkiCollector(Collector):
    app_label = "netbox_pki"
    kind = "cert"

    def collect(self, scope: Scope) -> tuple[list[Node], list[Edge]]:
        if scope.mode != "all":
            return [], []
        from netbox_pki.models import ACMEAccount, PkiCertificate, PkiCertificateAuthority

        nodes: list[Node] = []
        edges: list[Edge] = []

        for ca in PkiCertificateAuthority.objects.all():
            nodes.append(Node(nid("ca", ca.pk), ca.name, "ca"))
        for account in ACMEAccount.objects.all():
            nodes.append(
                Node(
                    nid("acme", account.pk),
                    account.contact_email,
                    "acme",
                    parent=nid("ca", account.ca_id),
                )
            )
        for cert in PkiCertificate.objects.all():
            nodes.append(
                Node(nid("cert", cert.pk), cert.common_name, "cert", parent=nid("ca", cert.ca_id))
            )
            if cert.service_instance_id:
                edges.append(
                    Edge(nid("cert", cert.pk), nid("svc", cert.service_instance_id), "secures")
                )
            if cert.acme_account_id:
                edges.append(Edge(nid("cert", cert.pk), nid("acme", cert.acme_account_id), "acme"))

        return nodes, edges
