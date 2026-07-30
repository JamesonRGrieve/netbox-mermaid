# SPDX-License-Identifier: AGPL-3.0-or-later
"""netbox-load-balancing-acl collector: the HAProxy frontend detail — ACL conditions, routing rules,
and bound TLS certificates — grouped under a synthetic node per upstream Listener (the frontend they
attach to). The Listener itself belongs to netbox-load-balancing, which the diagram does not model
directly, so it is represented as a lightweight container keyed by the listener's id. Member-HA rows
are omitted from the diagram for brevity and live in full in the SoT report. These objects are
frontend-scoped, not host-anchored, so they populate only in whole-SoT (``all``) scope. Optional —
skipped when the plugin is absent.
"""

from __future__ import annotations

from .base import Collector, Edge, Node, Scope, display, nid


class LbAclCollector(Collector):
    app_label = "netbox_load_balancing_acl"
    kind = "lbacl"

    def collect(self, scope: Scope) -> tuple[list[Node], list[Edge]]:
        if scope.mode != "all":
            return [], []
        from netbox_load_balancing_acl.models import (
            LBAcl,
            LBListenerCertificate,
            LBRoutingRule,
        )

        nodes: list[Node] = []
        listeners: dict[int, str] = {}  # listener_id -> label

        def child(prefix: str, obj: object, kind: str, label: str) -> None:
            listener = obj.listener
            listeners.setdefault(obj.listener_id, str(listener) if listener else f"Listener {obj.listener_id}")
            nodes.append(Node(nid(prefix, obj.pk), label, kind, parent=nid("lblistener", obj.listener_id)))

        for acl in LBAcl.objects.select_related("listener"):
            child("lbacl", acl, "lbacl", display(acl, "name"))
        for rule in LBRoutingRule.objects.select_related("listener"):
            child("lbrule", rule, "lbrule", rule.action_type)
        for cert in LBListenerCertificate.objects.select_related("listener"):
            child("lbcert", cert, "lbcert", str(cert.ssl_certificate))

        for listener_id, label in listeners.items():
            nodes.append(Node(nid("lblistener", listener_id), label, "lblistener"))

        return nodes, []
