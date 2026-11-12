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

import math
import re
from dataclasses import dataclass, replace

from .collectors.base import Edge, Node, Scope, dedupe_edges, dedupe_nodes

MERMAID_HEADER = "flowchart TD"
#: Views drawn left → right: ``all`` hangs every guest off its networks (left) and its cabling
#: (right); top-down, those links pin every guest of a hypervisor into one very wide row.
_LR_VIEWS = frozenset({"all"})
# Layout directive emitted ahead of the header: straight connectors (curved splines between many
# boxes read as spaghetti) and compact spacing so a site fits on one screen.
MERMAID_INIT = (
    '%%{init: {"flowchart": {"curve": "linear", "nodeSpacing": 28, "rankSpacing": 44, '
    '"padding": 12, "htmlLabels": true, "wrappingWidth": 400}}}%%'
)

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
    # host-role layer (netbox-services)
    "hostrole": ("#744210", "#f6e05e", "#ffffff"),
    "hostroleassign": ("#975a16", "#faf089", "#ffffff"),
    # inference (netbox-ai)
    "aicatalog": ("#44337a", "#d6bcfa", "#ffffff"),
    "aivariant": ("#553c9a", "#d6bcfa", "#ffffff"),
    "aideploy": ("#6b46c1", "#d6bcfa", "#ffffff"),
    "airoute": ("#805ad5", "#e9d8fd", "#ffffff"),
    "gpu": ("#22543d", "#9ae6b4", "#ffffff"),
    # cloudflare edge / LB
    "cftunnel": ("#9c4221", "#fbd38d", "#ffffff"),
    "cfingress": ("#c05621", "#fbd38d", "#ffffff"),
    "cfrecord": ("#b7791f", "#faf089", "#ffffff"),
    # DNS (netbox-dns)
    "dnszone": ("#3c366b", "#b794f4", "#ffffff"),
    "dnsrecord": ("#44337a", "#d6bcfa", "#ffffff"),
    "cflb": ("#c05621", "#fbd38d", "#ffffff"),
    "cfpool": ("#dd6b20", "#fbd38d", "#ffffff"),
    "cforigin": ("#ed8936", "#feebc8", "#ffffff"),
    "cfmonitor": ("#975a16", "#faf089", "#ffffff"),
    # load-balancer ACL layer
    "lblistener": ("#702459", "#fbb6ce", "#ffffff"),
    "lbrule": ("#97266d", "#fbb6ce", "#ffffff"),
    "lbacl": ("#b83280", "#fed7e2", "#ffffff"),
    "lbcert": ("#c53030", "#feb2b2", "#ffffff"),
    # firewall (netbox-pf)
    "pfgw": ("#9b2c2c", "#feb2b2", "#ffffff"),
    "pfgwgroup": ("#822727", "#fc8181", "#ffffff"),
    "pfalias": ("#c53030", "#feb2b2", "#ffffff"),
    # DHCP / L2 control plane
    "dhcp": ("#2c5282", "#90cdf4", "#ffffff"),
    "datalink": ("#2a4365", "#90cdf4", "#ffffff"),
    # WireGuard VPN
    "wgtunnel": ("#22543d", "#9ae6b4", "#ffffff"),
    "wgpeer": ("#276749", "#c6f6d5", "#ffffff"),
    # Reticulum
    "retnet": ("#44337a", "#d6bcfa", "#ffffff"),
    "retnode": ("#553c9a", "#e9d8fd", "#ffffff"),
    # MeshCore radio mesh
    "meshnet": ("#234e52", "#81e6d9", "#ffffff"),
    "meshnode": ("#285e61", "#b2f5ea", "#ffffff"),
    # ZFS storage
    "zfspool": ("#234e52", "#81e6d9", "#ffffff"),
    "zfsvdev": ("#2c7a7b", "#b2f5ea", "#ffffff"),
    # Proxmox guest extras
    "guestdev": ("#3e4c59", "#b8c1cc", "#ffffff"),
    "guestmount": ("#4a5568", "#cbd5e0", "#ffffff"),
    "location": ("#28333f", "#7b8794", "#f5f7fa"),
    "vlan": ("#1c2b36", "#d69e2e", "#f5f7fa"),
    "prefix": ("#744210", "#f6e05e", "#ffffff"),
}
# Pure layout containers (grid rows): drawn with no box at all.
_INVISIBLE_KINDS = frozenset({"row"})
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
    # new leaf kinds
    "gpu": ("{{", "}}"),
    "aivariant": ("([", "])"),
    "aideploy": ("([", "])"),
    "cfrecord": ("[/", "/]"),
    "dnsrecord": ("[/", "/]"),
    "cforigin": ("[(", ")]"),
    "cfmonitor": ("{{", "}}"),
    "lbcert": ("[/", "/]"),
    "zfsvdev": ("[(", ")]"),
    "wgpeer": ("(", ")"),
    "retnode": ("(", ")"),
    "meshnode": ("(", ")"),
    "pfalias": ("{{", "}}"),
    "dhcp": ("[(", ")]"),
    "prefix": ("[/", "/]"),
    "vlan": ("[[", "]]"),
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


# Children of a container are drawn grouped by kind (sub-containers first, then hosts, then
# detail), each group in natural order, so "dev 9" precedes "dev 10" and VLANs run in VID order.
_KIND_ORDER: dict[str, int] = {
    "tenant": 0, "site": 1, "row": 2, "location": 3, "cluster": 4, "device": 5, "vm": 6,
    "vlan": 7, "prefix": 8,
}


def _natural(text: str) -> list[object]:
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", text)]


def _child_key(node: Node) -> tuple[object, ...]:
    text = node.label.strip() or node.id
    return (_KIND_ORDER.get(node.kind, 50), _natural(text), node.id)


#: A container with more than this many independent units (single nodes, or clusters of siblings
#: joined only to each other) lays them out as a grid; up to this many read fine as one row.
_GRID_MIN = 6


@dataclass
class _Grid:
    """``_gridify`` result: nodes with the column wrappers added, and each column's member order."""

    nodes: list[Node]
    order: dict[str, list[str]]


def _gridify(nodes: list[Node], edges: list[Edge], direction: str = "TD") -> _Grid:
    """Lay each container's independent children out as a grid of invisible columns.

    Dagre puts every unconnected sibling (or sibling cluster) side by side, so twenty guests, VLAN
    cards or network↔host clusters become one strip thousands of pixels wide. Here a container's
    children are split into **units**: connected components of the edges that run between them
    (an edge to a descendant counts for the child holding it). A unit with an edge leaving the
    container stays put. The rest are dealt, in order, into ``≈√`` columns: invisible ``row``-kind
    containers with ``direction LR`` — Mermaid stacks a column's separate units vertically, lays each
    unit's own edges left → right, and places the columns side by side. No layout links are added
    (links between subgraphs crash Mermaid's dagre layout).

    Inside a unit the members are ordered so dagre draws few crossings: edge sources first (hosts
    with the most links pull their networks together), then targets by the mean position of their
    sources. Dagre keeps definition order where it can, so this order is what reaches the screen.
    """
    by_id = {n.id: n for n in nodes}
    children: dict[str, list[Node]] = {}
    for node in nodes:
        if node.parent and node.parent in by_id:
            children.setdefault(node.parent, []).append(node)

    def chain(node_id: str) -> list[str]:
        out = [node_id]
        while (parent := by_id[out[-1]].parent) and parent in by_id:
            out.append(parent)
        return out

    chains = {n.id: chain(n.id) for n in nodes}

    def flow(container: str) -> str:  # the direction a container lays its children out in
        return next((by_id[c].direction for c in chains[container] if by_id[c].direction), direction)

    order: dict[str, list[str]] = {}
    moved: dict[str, str] = {}
    pinned: dict[str, str] = {}  # gridded container -> the flow its columns assume
    columns: list[Node] = []
    for parent_id, kids in children.items():
        kid_ids = {k.id for k in kids}

        def holder(node_id: str) -> str | None:  # the child of parent_id containing node_id
            return next((c for c in chains.get(node_id, []) if c in kid_ids), None)

        links: dict[str, set[str]] = {k: set() for k in kid_ids}
        inner: list[tuple[str, str]] = []
        anchored: set[str] = set()
        for edge in edges:
            a, b = holder(edge.src), holder(edge.dst)
            if a and b:
                if a != b:
                    links[a].add(b)
                    links[b].add(a)
                    inner.append((a, b))
            elif a or b:
                anchored.add(a or b)  # an edge leaves the container

        units: list[list[str]] = []
        seen: set[str] = set()
        for kid in sorted(kids, key=_child_key):
            if kid.id in seen:
                continue
            unit, stack = [], [kid.id]
            while stack:
                cur = stack.pop()
                if cur not in seen:
                    seen.add(cur)
                    unit.append(cur)
                    stack.extend(links[cur])
            if not anchored.intersection(unit):
                units.append(_unit_order(unit, inner, by_id))
        if len(units) <= _GRID_MIN:
            continue
        # Read a unit by its hub side (edge sources: the network in a network ↔ hosts cluster), so
        # clusters run in VLAN order rather than by whichever host name sorts first.
        sources = {a for a, _ in inner}
        units.sort(key=lambda u: min(_child_key(by_id[m]) for m in ([m for m in u if m in sources] or u)))

        weights = [_unit_rows(unit, inner) for unit in units]
        if all(len(unit) == 1 for unit in units):
            # Boxes holding boxes (VLAN cards, hosts with guests) are about twice as wide as tall,
            # so a grid of them takes half as many columns to come out roughly square.
            boxes = sum(1 for unit in units if unit[0] in children)
            cols = math.ceil(math.sqrt(len(units) / (2 if boxes > len(units) / 2 else 1)))
        else:
            cols = max(1, round(math.sqrt(sum(weights) / 3)))
        cols = min(cols, len(units))
        target = sum(weights) / cols
        col, filled = 0, 0.0
        for unit, weight in zip(units, weights):
            if filled >= target - 1e-9 and col < cols - 1 and filled:
                col, filled = col + 1, 0.0
            col_id = f"{parent_id}__col{col}"
            if col_id not in order:
                # A column runs across its parent's flow: LR columns side by side under a top-down
                # parent, TB rows stacked under a left-to-right one.
                along = flow(parent_id)
                across = "LR" if along in ("TD", "TB", "BT") else "TB"
                pinned[parent_id] = "TB" if across == "LR" else "LR"
                columns.append(Node(col_id, "", "row", parent=parent_id, direction=across))
                order[col_id] = []
            order[col_id].extend(unit)
            for member in unit:
                moved[member] = col_id
            filled += weight
    if not moved:
        return _Grid(nodes, order)
    # A subgraph inherits its parent's direction, so a box moved into an LR column would stack its
    # own contents vertically; pin it back to top-down.
    # A container left without a direction is laid out by Mermaid in a direction of its own choosing
    # (not reliably its parent's), so every gridded container is pinned to the flow its columns
    # were built for.
    rebuilt = []
    for n in nodes:
        if n.id in moved:
            n = replace(n, parent=moved[n.id], direction=n.direction or ("TB" if n.id in children else None))
        if n.id in pinned and not n.direction:
            n = replace(n, direction=pinned[n.id])
        rebuilt.append(n)
    return _Grid(rebuilt + columns, order)


def _unit_order(unit: list[str], inner: list[tuple[str, str]], by_id: dict[str, Node]) -> list[str]:
    """Order one unit's members for few crossings: sources, then targets by mean source position."""
    if len(unit) == 1:
        return unit
    members = set(unit)
    pairs = [(a, b) for a, b in inner if a in members and b in members]
    sources = {a for a, _ in pairs}
    targets = [m for m in unit if m not in sources]
    nbrs: dict[str, list[str]] = {m: [] for m in unit}
    for a, b in pairs:
        nbrs[a].append(b)
        nbrs[b].append(a)

    def key(member: str) -> tuple[object, ...]:
        return _child_key(by_id[member])

    placed: list[str] = []
    for target in sorted(targets, key=lambda t: (-len(nbrs[t]), key(t))):
        for src in sorted(set(nbrs[target]) & sources, key=key):
            if src not in placed:
                placed.append(src)
    placed += sorted(sources - set(placed), key=key)
    if not targets:
        return placed  # not two-layered (e.g. a cable chain): dagre orders it itself

    def mean(member: str, index: dict[str, int], fallback: float) -> float:
        pos = [index[n] for n in nbrs[member] if n in index]
        return sum(pos) / len(pos) if pos else fallback

    def crossings(left: list[str], right: list[str]) -> int:
        li = {n: i for i, n in enumerate(left)}
        ri = {n: i for i, n in enumerate(right)}
        segs = [(li[a], ri[b]) for a, b in pairs if a in li and b in ri]
        segs += [(li[b], ri[a]) for a, b in pairs if b in li and a in ri]
        return sum(1 for i, (a1, b1) in enumerate(segs) for a2, b2 in segs[i + 1 :] if (a1 - a2) * (b1 - b2) < 0)

    # Two-layer barycenter sweeps (sources ↔ targets), keeping the order with fewest crossings.
    left = placed
    right = sorted(targets, key=lambda t: (mean(t, {n: i for i, n in enumerate(left)}, len(left)), key(t)))
    best = (crossings(left, right), left, right)
    for _ in range(8):
        ri = {n: i for i, n in enumerate(right)}
        left = sorted(left, key=lambda n: (mean(n, ri, len(right)), key(n)))
        li = {n: i for i, n in enumerate(left)}
        right = sorted(right, key=lambda n: (mean(n, li, len(left)), key(n)))
        score = crossings(left, right)
        if score < best[0]:
            best = (score, left, right)
        if score == 0:
            break
    return best[1] + best[2]


def _unit_rows(unit: list[str], inner: list[tuple[str, str]]) -> int:
    """Rough height of a unit laid out left → right: its longer side (sources vs targets)."""
    members = set(unit)
    sources = {a for a, b in inner if a in members and b in members}
    return max(1, len(sources), len(members) - len(sources))


def _emit_order(
    kids: list[Node], children: dict[str, list[Node]], fixed: list[str] | None = None
) -> list[Node]:
    """Leaves in order, then sub-containers in *reverse* order: Mermaid's layout places sibling
    subgraphs in the reverse of their definition order, so this draws them in natural order (VLAN 4
    before VLAN 60, column 0 left of column 1). ``fixed`` is a grid column's computed member order;
    otherwise siblings sort naturally."""
    if fixed:
        rank = {node_id: i for i, node_id in enumerate(fixed)}
        ordered = sorted(kids, key=lambda n: rank.get(n.id, len(rank)))
    else:
        ordered = sorted(kids, key=_child_key)
    containers = {n.id for n in ordered if n.id in children}
    return [n for n in ordered if n.id not in containers] + [
        n for n in reversed(ordered) if n.id in containers
    ]


def _color_line(kind: str) -> str:
    fill, stroke, text = _KIND_COLORS.get(kind, _DEFAULT_COLOR)
    return f"fill:{fill},stroke:{stroke},color:{text}"


def render(nodes: list[Node], edges: list[Edge], direction: str = "TD") -> Diagram:
    """Render a (already scoped / optionally sanitized) node+edge set to a Mermaid flowchart
    (``direction`` ``TD`` or ``LR``)."""
    nodes = dedupe_nodes(nodes)
    edges = dedupe_edges(edges)
    grid = _gridify(nodes, edges, direction)
    nodes = grid.nodes
    node_by_id = {n.id: n for n in nodes}
    edges = [e for e in dedupe_edges(edges) if e.src in node_by_id and e.dst in node_by_id]

    children: dict[str, list[Node]] = {}
    roots: list[Node] = []
    for node in nodes:
        if node.parent and node.parent in node_by_id:
            children.setdefault(node.parent, []).append(node)
        else:
            roots.append(node)

    header = MERMAID_HEADER if direction != "LR" else "flowchart LR"
    lines: list[str] = [MERMAID_INIT, header]
    leaf_kinds: set[str] = set()
    container_ids: list[tuple[str, str]] = []  # (id, kind) for style lines
    leaf_ids: list[tuple[str, str]] = []  # (id, kind) for class lines

    def emit(node: Node, depth: int) -> None:
        pad = _INDENT * depth
        kids = children.get(node.id)
        if kids:
            title = escape_label(node.label) if node.label.strip() else '" "'
            lines.append(f"{pad}subgraph {node.id}[{title}]")
            if node.direction in ("TB", "TD", "LR", "RL", "BT"):
                lines.append(f"{pad}{_INDENT}direction {node.direction}")
            elif direction != "TD":
                # Mermaid lays a subgraph with no direction of its own out top-down whatever the
                # diagram's direction, so a left-to-right diagram states it on every box.
                lines.append(f"{pad}{_INDENT}direction {direction}")
            container_ids.append((node.id, node.kind))
            for kid in _emit_order(kids, children, grid.order.get(node.id)):
                emit(kid, depth + 1)
            lines.append(f"{pad}end")
        else:
            open_d, close_d = _KIND_SHAPE.get(node.kind, _DEFAULT_SHAPE)
            lines.append(f"{pad}{node.id}{open_d}{escape_label(node.label)}{close_d}")
            leaf_kinds.add(node.kind)
            leaf_ids.append((node.id, node.kind))

    for root in _emit_order(roots, children):
        emit(root, 1)

    # Edges in the order their endpoints were emitted: dagre's initial ordering walks edges in
    # definition order, so this keeps the crossing-reduced order computed by ``_gridify``.
    position = {node_id: i for i, (node_id, _kind) in enumerate(leaf_ids + container_ids)}
    for edge in sorted(
        edges, key=lambda e: (position.get(e.src, 0), position.get(e.dst, 0), e.src, e.dst, e.label)
    ):
        link = "---" if edge.style == "line" else "-->"
        if edge.label:
            lines.append(f"{_INDENT}{edge.src} {link}|{escape_label(edge.label)}| {edge.dst}")
        else:
            lines.append(f"{_INDENT}{edge.src} {link} {edge.dst}")

    for kind in sorted(leaf_kinds):
        lines.append(f"{_INDENT}classDef {kind} {_color_line(kind)};")
    for node_id, kind in leaf_ids:
        lines.append(f"{_INDENT}class {node_id} {kind};")
    for node_id, kind in container_ids:
        if kind in _INVISIBLE_KINDS:
            lines.append(f"{_INDENT}style {node_id} fill:none,stroke:none;")
        else:
            lines.append(f"{_INDENT}style {node_id} {_color_line(kind)};")

    return Diagram(
        mermaid="\n".join(lines),
        node_count=sum(1 for n in nodes if n.kind not in _INVISIBLE_KINDS),
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
    diagram = render(nodes, edges, "LR" if scope.view in _LR_VIEWS else "TD")
    diagram.sanitized = sanitize
    return diagram
