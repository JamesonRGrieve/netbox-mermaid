# SPDX-License-Identifier: AGPL-3.0-or-later
"""netbox-email collector: MailDomains (nested under the ServiceInstance that serves them) with
their Mailboxes and Aliases as nested detail, plus standalone MailRelays. Not host-anchored, so it
populates only in whole-SoT (``all``) scope. Optional — skipped when the plugin is absent.
"""

from __future__ import annotations

from .base import Collector, Edge, Node, Scope, nid


class EmailCollector(Collector):
    app_label = "netbox_email"
    kind = "maildomain"

    def collect(self, scope: Scope) -> tuple[list[Node], list[Edge]]:
        if scope.mode != "all":
            return [], []
        from netbox_email.models import MailAlias, Mailbox, MailDomain, MailRelay

        nodes: list[Node] = []
        edges: list[Edge] = []

        for domain in MailDomain.objects.all():
            parent = nid("svc", domain.service_instance_id) if domain.service_instance_id else None
            nodes.append(
                Node(nid("maildomain", domain.pk), domain.name, "maildomain", parent=parent)
            )
        for mailbox in Mailbox.objects.all():
            nodes.append(
                Node(
                    nid("mailbox", mailbox.pk),
                    mailbox.local_part,
                    "mailbox",
                    parent=nid("maildomain", mailbox.domain_id),
                )
            )
        for alias in MailAlias.objects.all():
            nodes.append(
                Node(
                    nid("mailalias", alias.pk),
                    alias.source_local_part,
                    "mailalias",
                    parent=nid("maildomain", alias.domain_id),
                )
            )
        for relay in MailRelay.objects.all():
            parent = nid("svc", relay.service_instance_id) if relay.service_instance_id else None
            nodes.append(Node(nid("mailrelay", relay.pk), relay.name, "mailrelay", parent=parent))

        return nodes, edges
