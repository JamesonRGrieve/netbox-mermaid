# SPDX-License-Identifier: AGPL-3.0-or-later
"""Assemble collected :class:`~netbox_mermaid.collectors.base.Node` + ``Edge`` records into one
well-structured, parseable Mermaid ``flowchart TD``.

Structure: a ``subgraph`` per container (Site → host → service instance → per-service detail),
labelled cross-edges between vertices (WP→DB, cert→instance, HA mirror, cluster membership,
federation peers), a ``classDef`` per kind (colour + shape), and a ``class``/``style`` assignment
per vertex. All label text is escaped for Mermaid's parser. ``build_diagram`` is the orchestrator
the view + API call: it runs the registry, optionally the sanitizer, then renders.
"""

from __future__ import annotations

from dataclasses import dataclass

from .collectors.base import Edge, Node, Scope, dedupe_edges, dedupe_nodes

MERMAID_HEADER = "flowchart TD"

# kind -> (fill, stroke, text) hex colours for classDef / subgraph style.
_KIND_COLORS: dict[str, tuple[str, str, str]] = {
    "site": ("#1f2933", "#9aa5b1", "#f5f7fa"),
    "device": ("#334e68", "#9fb3c8", "#f0f4f8"),
    "vm": ("#243b53", "#829ab1", "#f0f4f8"),
    "tenant": ("#3e4c59", "#b8c1cc", "#f5f7fa"),
    "service": ("#2b6cb0", "#90cdf4", "#ffffff"),
    "dbserver": ("#22543d", "#9ae6b4", "#ffffff"),
    "database": ("#276749", "#9ae6b4", "#ffffff"),
    "dbuser": ("#2f855a", "#c6f6d5", "#ffffff"),
    "cluster": ("#744210", "#f6e05e", "#ffffff"),
    "webserver": ("#702459", "#fbb6ce", "#ffffff"),
    "vhost": ("#97266d", "#fbb6ce", "#ffffff"),
    "fpmpool": ("#b83280", "#fed7e2", "#ffffff"),
    "wpsite": ("#5521b5", "#d6bcfa", "#ffffff"),
    "wpcomponent": ("#6b46c1", "#e9d8fd", "#ffffff"),
    "ca": ("#9b2c2c", "#feb2b2", "#ffffff"),
    "cert": ("#c53030", "#feb2b2", "#ffffff"),
    "acme": ("#9c4221", "#fbd38d", "#ffffff"),
    "maildomain": ("#285e61", "#81e6d9", "#ffffff"),
    "mailbox": ("#2c7a7b", "#b2f5ea", "#ffffff"),
    "mailalias": ("#319795", "#b2f5ea", "#ffffff"),
    "mailrelay": ("#234e52", "#81e6d9", "#ffffff"),
    "realm": ("#3182ce", "#bee3f8", "#ffffff"),
    "peer": ("#2b6cb0", "#bee3f8", "#ffffff"),
}
_DEFAULT_COLOR = ("#4a5568", "#a0aec0", "#ffffff")

# kind -> (open, close) Mermaid shape delimiters for *leaf* nodes (containers become subgraphs).
_KIND_SHAPE: dict[str, tuple[str, str]] = {
    "service": ("([", "])"),
    "dbserver": ("[(", ")]"),
    "database": ("[(", ")]"),
    "cluster": ("{{", "}}"),
    "tenant": ("{{", "}}"),
    "ca": ("{{", "}}"),
    "vhost": ("[/", "/]"),
    "cert": ("[/", "/]"),
    "wpsite": ("([", "])"),
    "maildomain": ("([", "])"),
    "realm": ("([", "])"),
    "vm": ("(", ")"),
}
_DEFAULT_SHAPE = ("[", "]")

_INDENT = "    "


@dataclass
class Diagram:
    """Render result returned to the view + API."""

    mermaid: str
    node_count: int
    edge_count: int
    sanitized: bool


def escape_label(text: object) -> str:
    """Return a Mermaid-safe, double-quoted label. Order matters: ``#`` is escaped first so the
    numeric entities inserted afterwards are not themselves re-escaped."""
    s = str(text)
    s = s.replace("#", "#35;")
    s = s.replace('"', "#34;")
    s = s.replace("<", "#60;")
    s = s.replace(">", "#62;")
    s = s.replace("|", "#124;")
    s = s.replace("{", "#123;").replace("}", "#125;")
    s = s.replace("\n", "<br/>")
    return f'"{s}"'


def _color_line(kind: str) -> str:
    fill, stroke, text = _KIND_COLORS.get(kind, _DEFAULT_COLOR)
    return f"fill:{fill},stroke:{stroke},color:{text}"


def render(nodes: list[Node], edges: list[Edge]) -> Diagram:
    """Render a (already scoped / optionally sanitized) node+edge set to a Mermaid flowchart."""
    nodes = dedupe_nodes(nodes)
    node_by_id = {n.id: n for n in nodes}
    edges = [e for e in dedupe_edges(edges) if e.src in node_by_id and e.dst in node_by_id]

    children: dict[str, list[Node]] = {}
    roots: list[Node] = []
    for node in nodes:
        if node.parent and node.parent in node_by_id:
            children.setdefault(node.parent, []).append(node)
        else:
            roots.append(node)

    lines: list[str] = [MERMAID_HEADER]
    leaf_kinds: set[str] = set()
    container_ids: list[tuple[str, str]] = []  # (id, kind) for style lines
    leaf_ids: list[tuple[str, str]] = []  # (id, kind) for class lines

    def emit(node: Node, depth: int) -> None:
        pad = _INDENT * depth
        kids = children.get(node.id)
        if kids:
            lines.append(f"{pad}subgraph {node.id}[{escape_label(node.label)}]")
            container_ids.append((node.id, node.kind))
            for kid in sorted(kids, key=lambda x: x.id):
                emit(kid, depth + 1)
            lines.append(f"{pad}end")
        else:
            open_d, close_d = _KIND_SHAPE.get(node.kind, _DEFAULT_SHAPE)
            lines.append(f"{pad}{node.id}{open_d}{escape_label(node.label)}{close_d}")
            leaf_kinds.add(node.kind)
            leaf_ids.append((node.id, node.kind))

    for root in sorted(roots, key=lambda x: x.id):
        emit(root, 1)

    for edge in sorted(edges, key=lambda e: (e.src, e.dst, e.label)):
        if edge.label:
            lines.append(f"{_INDENT}{edge.src} -->|{escape_label(edge.label)}| {edge.dst}")
        else:
            lines.append(f"{_INDENT}{edge.src} --> {edge.dst}")

    for kind in sorted(leaf_kinds):
        lines.append(f"{_INDENT}classDef {kind} {_color_line(kind)};")
    for node_id, kind in leaf_ids:
        lines.append(f"{_INDENT}class {node_id} {kind};")
    for node_id, kind in container_ids:
        lines.append(f"{_INDENT}style {node_id} {_color_line(kind)};")

    return Diagram(
        mermaid="\n".join(lines),
        node_count=len(nodes),
        edge_count=len(edges),
        sanitized=False,
    )


def build_diagram(scope: Scope | None = None, sanitize: bool = False) -> Diagram:
    """Full pipeline: collect every available source, optionally sanitize, render."""
    from .collectors.registry import collect_all
    from .sanitizer import Sanitizer

    scope = scope or Scope()
    nodes, edges = collect_all(scope)
    if sanitize:
        nodes, edges = Sanitizer().sanitize(nodes, edges)
    diagram = render(nodes, edges)
    diagram.sanitized = sanitize
    return diagram
