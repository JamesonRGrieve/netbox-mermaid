# SPDX-License-Identifier: AGPL-3.0-or-later
"""Public-sharing sanitizer: transform nodes/edges so the rendered diagram is safe to post
publicly (a Facebook group, a blog post) while preserving STRUCTURE + kinds + relationships.

Threat model — the output must leak **nothing** identifying:
  * real hostnames / FQDNs / object names → deterministic generic per-kind labels ("Database 1",
    "Web Host 2", "VM 3");
  * NetBox object PKs / ids → stable synthetic ids (``DB1``, ``H2`` …), never the real pk;
  * IP addresses / CIDRs → ``«ip»``; e-mail addresses → ``«email»``;
  * OpenBao / secret / credential path references → ``«secret»``;
  * tenant / customer / org names → ``Tenant A``, ``Tenant B`` …;
  * ``raw_attrs`` (which may carry serials, asset tags, secret refs, internal domains) → dropped.

The mapping is deterministic **per run**: the same real value always maps to the same generic
label, so cross-links stay coherent. Node/edge COUNTS are preserved — structure is intact.
"""

from __future__ import annotations

import re
from collections import defaultdict

from .collectors.base import Edge, Node

# kind -> human generic prefix for the redacted label.
_GENERIC_LABEL: dict[str, str] = {
    "site": "Site",
    "device": "Host",
    "vm": "VM",
    "tenant": "Tenant",
    "service": "Service",
    "dbserver": "Database Server",
    "database": "Database",
    "dbuser": "DB User",
    "cluster": "Cluster",
    "webserver": "Web Host",
    "vhost": "Virtual Host",
    "fpmpool": "FPM Pool",
    "wpsite": "WordPress Site",
    "wpcomponent": "WP Component",
    "ca": "Certificate Authority",
    "cert": "Certificate",
    "acme": "ACME Account",
    "maildomain": "Mail Domain",
    "mailbox": "Mailbox",
    "mailalias": "Mail Alias",
    "mailrelay": "Mail Relay",
    "realm": "Federation Realm",
    "peer": "Federation Peer",
    "hostrole": "Host Role",
    "hostroleassign": "Host Role Assignment",
    "aicatalog": "Model Catalog",
    "aivariant": "Model Variant",
    "aideploy": "Inference Deployment",
    "airoute": "Gateway Route",
    "gpu": "GPU",
    "cftunnel": "Cloudflare Tunnel",
    "cfingress": "Tunnel Ingress",
    "cfrecord": "DNS Record",
    "cflb": "Cloudflare Load Balancer",
    "cfpool": "LB Pool",
    "cforigin": "LB Origin",
    "cfmonitor": "LB Monitor",
    "lblistener": "LB Listener",
    "lbrule": "LB Routing Rule",
    "lbacl": "LB ACL",
    "lbcert": "LB Certificate",
    "pfgw": "Gateway",
    "pfgwgroup": "Gateway Group",
    "pfalias": "Firewall Alias",
    "dhcp": "DHCP Scope",
    "datalink": "L2 Config",
    "wgtunnel": "WireGuard Tunnel",
    "wgpeer": "WireGuard Peer",
    "retnet": "Reticulum Network",
    "retnode": "Reticulum Node",
    "meshnet": "Mesh Network",
    "meshnode": "Mesh Node",
    "zfspool": "ZFS Pool",
    "zfsvdev": "ZFS Vdev",
    "guestdev": "Guest Device",
    "guestmount": "Guest Mount",
}

# kind -> synthetic id abbreviation (hides the real pk while keeping the kind legible).
_ID_ABBR: dict[str, str] = {
    "site": "S",
    "device": "H",
    "vm": "V",
    "tenant": "T",
    "service": "SVC",
    "dbserver": "DBS",
    "database": "DB",
    "dbuser": "DBU",
    "cluster": "CL",
    "webserver": "W",
    "vhost": "VH",
    "fpmpool": "FPM",
    "wpsite": "WP",
    "wpcomponent": "WC",
    "ca": "CA",
    "cert": "CRT",
    "acme": "AC",
    "maildomain": "MD",
    "mailbox": "MB",
    "mailalias": "MA",
    "mailrelay": "MR",
    "realm": "RLM",
    "peer": "PR",
    "hostrole": "HR",
    "hostroleassign": "HRA",
    "aicatalog": "AMC",
    "aivariant": "AMV",
    "aideploy": "AID",
    "airoute": "AGR",
    "gpu": "GPU",
    "cftunnel": "CFT",
    "cfingress": "CFI",
    "cfrecord": "CFR",
    "cflb": "CFLB",
    "cfpool": "CFP",
    "cforigin": "CFO",
    "cfmonitor": "CFM",
    "lblistener": "LBL",
    "lbrule": "LBR",
    "lbacl": "LBA",
    "lbcert": "LBC",
    "pfgw": "GW",
    "pfgwgroup": "GWG",
    "pfalias": "FWA",
    "dhcp": "DH",
    "datalink": "L2",
    "wgtunnel": "WGT",
    "wgpeer": "WGP",
    "retnet": "RNET",
    "retnode": "RNODE",
    "meshnet": "MNET",
    "meshnode": "MNODE",
    "zfspool": "ZP",
    "zfsvdev": "ZV",
    "guestdev": "GD",
    "guestmount": "GM",
}

_IP_V4 = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}(?:/\d{1,2})?\b")
_IP_V6 = re.compile(r"\b(?:[0-9a-fA-F]{0,4}:){2,7}[0-9a-fA-F]{0,4}(?:/\d{1,3})?\b")
_EMAIL = re.compile(r"\b[\w.+-]+@[\w.-]+\.\w+\b")
_SECRET = re.compile(r"\b(?:secret|kv|openbao|bao|vault|credential)[\w./:-]*", re.IGNORECASE)

_IP_PLACEHOLDER = "«ip»"
_EMAIL_PLACEHOLDER = "«email»"
_SECRET_PLACEHOLDER = "«secret»"


def _letter_suffix(index: int) -> str:
    """1→A, 2→B, … 26→Z, 27→AA (spreadsheet-column style)."""
    letters = ""
    while index > 0:
        index, rem = divmod(index - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


class Sanitizer:
    """Stateful, deterministic per-run redactor. Instantiate once per :meth:`sanitize` call."""

    def __init__(self) -> None:
        self._id_map: dict[str, str] = {}
        self._counter: dict[str, int] = defaultdict(int)
        # real free-text value (e.g. a hostname reused in an edge label) -> its generic placeholder,
        # so the same real value redacts to the same token everywhere.
        self._value_map: dict[str, str] = {}

    def sanitize(self, nodes: list[Node], edges: list[Edge]) -> tuple[list[Node], list[Edge]]:
        # Pass 1 — sort by original id so numbering is deterministic regardless of collector order
        # (same input graph → byte-identical output); assign every synthetic id + generic label.
        generic_of: dict[str, str] = {}
        ordered = sorted(nodes, key=lambda n: n.id)
        for node in ordered:
            new_id, generic = self._redact_node(node)
            self._id_map[node.id] = new_id
            generic_of[node.id] = generic
            if node.label:
                self._value_map[node.label] = generic

        # Pass 2 — rebuild nodes now that every id is mapped (a parent may sort after its child).
        clean_nodes = [
            Node(
                id=self._id_map[node.id],
                label=generic_of[node.id],
                kind=node.kind,
                parent=self._id_map.get(node.parent) if node.parent else None,
                raw_attrs={},
            )
            for node in ordered
        ]

        clean_edges: list[Edge] = []
        for edge in edges:
            src = self._id_map.get(edge.src)
            dst = self._id_map.get(edge.dst)
            if src is None or dst is None:
                continue  # endpoint fell outside the graph; drop to keep output coherent
            clean_edges.append(Edge(src=src, dst=dst, label=self._scrub_text(edge.label)))
        return clean_nodes, clean_edges

    def _redact_node(self, node: Node) -> tuple[str, str]:
        self._counter[node.kind] += 1
        index = self._counter[node.kind]
        abbr = _ID_ABBR.get(node.kind, node.kind[:3].upper())
        new_id = f"{abbr}{index}"
        base = _GENERIC_LABEL.get(node.kind, node.kind.replace("_", " ").title())
        suffix = _letter_suffix(index) if node.kind == "tenant" else str(index)
        return new_id, f"{base} {suffix}"

    def _scrub_text(self, text: str) -> str:
        if not text:
            return text
        out = text
        # Replace any known real node label first (a hostname reused in an edge verb).
        for real, placeholder in self._value_map.items():
            if real and real in out:
                out = out.replace(real, placeholder)
        out = _IP_V4.sub(_IP_PLACEHOLDER, out)
        out = _IP_V6.sub(_IP_PLACEHOLDER, out)
        out = _EMAIL.sub(_EMAIL_PLACEHOLDER, out)
        out = _SECRET.sub(_SECRET_PLACEHOLDER, out)
        return out
