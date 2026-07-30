# SPDX-License-Identifier: AGPL-3.0-or-later
"""Shared collector primitives: the typed graph node/edge, the scope filter, the id scheme,
and the :class:`Collector` base every source module subclasses.

A collector introspects exactly one NetBox source (core, or one in-house plugin) and yields
:class:`Node` + :class:`Edge` records. Plugin collectors are **optional**: :meth:`Collector.available`
gates on ``django.apps.apps.is_installed(app_label)`` so an absent plugin is silently skipped, never
an error. Adding a new source is a one-file drop-in that subclasses :class:`Collector` and is
registered in ``registry.py``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable


# --- id scheme -------------------------------------------------------------------------------
# Every node id is ``<prefix>_<pk>``. Cross-plugin edges reconstruct a peer's id from the same
# (prefix, pk) pair without importing the peer collector, so references stay consistent even when
# the owning collector's plugin is absent (the edge is then dropped by the builder).
def nid(prefix: str, pk: object) -> str:
    """Build a stable, Mermaid-safe node id from a kind prefix and an object pk."""
    return f"{prefix}_{pk}"


@dataclass(frozen=True)
class Node:
    """One graph vertex.

    ``id``       — unique, Mermaid-safe (see :func:`nid`).
    ``label``    — human display text (escaped at render time, not here).
    ``kind``     — semantic class driving colour/shape + the sanitizer's per-kind counter.
    ``parent``   — id of the container node this nests under (site→host→instance→detail); ``None``
                   for a top-level node. Drives Mermaid ``subgraph`` nesting.
    ``raw_attrs``— extra identifying detail for tooltips; **dropped** entirely by the sanitizer.
    """

    id: str
    label: str
    kind: str
    parent: str | None = None
    raw_attrs: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Edge:
    """One directed cross-link. ``label`` is the relationship verb (e.g. ``"reads"``)."""

    src: str
    dst: str
    label: str = ""


@dataclass(frozen=True)
class Scope:
    """A view window over the SoT so large deployments stay readable.

    ``mode`` is one of ``all`` | ``site`` | ``device`` | ``vm``; the matching id narrows the graph.
    Collectors ask the membership helpers whether a given host/site belongs in the window.
    """

    mode: str = "all"
    site_id: int | None = None
    device_id: int | None = None
    vm_id: int | None = None

    @classmethod
    def from_params(cls, params: dict[str, str]) -> Scope:
        """Build a scope from GET params (``scope``/``site``/``device``/``vm``)."""
        site = _int_or_none(params.get("site"))
        device = _int_or_none(params.get("device"))
        vm = _int_or_none(params.get("vm"))
        mode = params.get("scope") or (
            "device" if device else "vm" if vm else "site" if site else "all"
        )
        return cls(mode=mode, site_id=site, device_id=device, vm_id=vm)

    def includes_site(self, site_id: int | None) -> bool:
        if self.mode == "all":
            return True
        if self.mode == "site":
            return site_id == self.site_id
        # device/vm scopes keep the containing site as a shell only via includes_device/vm.
        return True

    def includes_device(self, device_id: int | None, site_id: int | None) -> bool:
        if self.mode == "all":
            return True
        if self.mode == "site":
            return site_id == self.site_id
        if self.mode == "device":
            return device_id == self.device_id
        return False  # vm scope excludes devices

    def includes_vm(self, vm_id: int | None, site_id: int | None) -> bool:
        if self.mode == "all":
            return True
        if self.mode == "site":
            return site_id == self.site_id
        if self.mode == "vm":
            return vm_id == self.vm_id
        return False  # device scope excludes vms


def _int_or_none(value: str | None) -> int | None:
    if not value:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


class Collector:
    """Base for every source collector.

    Subclasses set :attr:`app_label` (empty string for always-present core models) and implement
    :meth:`collect`. :meth:`available` gates plugin collectors on installation so an absent plugin
    is a graceful skip. Import the collector's models **inside** :meth:`collect` (not at module top)
    so a missing plugin never breaks import of this package.
    """

    app_label: str = ""
    kind: str = "generic"

    def available(self) -> bool:
        """True when this collector's source is present. Core (empty label) is always available."""
        if not self.app_label:
            return True
        try:
            from django.apps import apps

            return apps.is_installed(self.app_label)
        except Exception:
            return False

    def collect(self, scope: Scope) -> tuple[list[Node], list[Edge]]:
        """Return this source's nodes + edges within ``scope``. Overridden by subclasses."""
        raise NotImplementedError

    def safe_collect(self, scope: Scope) -> tuple[list[Node], list[Edge]]:
        """Collect with a guard: an unavailable source yields nothing; an import/query error from a
        present-but-incompatible plugin degrades to empty rather than failing the whole diagram."""
        if not self.available():
            return [], []
        try:
            return self.collect(scope)
        except Exception:  # a single flaky source must not sink the whole SoT diagram
            return [], []


def dedupe_nodes(nodes: Iterable[Node]) -> list[Node]:
    """Keep the first node seen per id (collectors may independently reference the same vertex)."""
    seen: dict[str, Node] = {}
    for node in nodes:
        seen.setdefault(node.id, node)
    return list(seen.values())


def dedupe_edges(edges: Iterable[Edge]) -> list[Edge]:
    """Keep one edge per (src, dst, label)."""
    seen: dict[tuple[str, str, str], Edge] = {}
    for edge in edges:
        seen.setdefault((edge.src, edge.dst, edge.label), edge)
    return list(seen.values())


# --- host resolution (shared by every host-anchored collector) -------------------------------
# These operate on already-loaded ORM objects only — no model imports — so they live here and
# keep collectors DRY. A host-anchored object exposes ``device``/``virtual_machine`` FKs.
def vm_site_id(vm: object) -> int | None:
    """A VM's effective site: its own ``site`` if set, else its cluster's site."""
    site_id = getattr(vm, "site_id", None)
    if site_id:
        return site_id
    cluster = getattr(vm, "cluster", None)
    return getattr(cluster, "site_id", None) if cluster is not None else None


def host_ref(obj: object) -> tuple[str | None, int | None]:
    """Return (container node id, site id) for an object's host (device XOR virtual_machine)."""
    if getattr(obj, "device_id", None):
        return nid("dev", obj.device_id), getattr(obj.device, "site_id", None)
    if getattr(obj, "virtual_machine_id", None):
        return nid("vm", obj.virtual_machine_id), vm_site_id(obj.virtual_machine)
    return None, None


def host_in_scope(scope: Scope, obj: object) -> bool:
    """True when an object's host falls inside ``scope`` (device XOR virtual_machine)."""
    if scope.mode == "all":
        return True
    if getattr(obj, "device_id", None):
        return scope.includes_device(obj.device_id, getattr(obj.device, "site_id", None))
    if getattr(obj, "virtual_machine_id", None):
        return scope.includes_vm(obj.virtual_machine_id, vm_site_id(obj.virtual_machine))
    return False


def display(obj: object, *fields: str) -> str:
    """First truthy attribute among ``fields`` (stringified), else the object's ``str()``. Lets a
    collector prefer a short ``name``/``slug`` label but fall back to the model's own ``__str__`` for
    the many plugin models whose only display is a composite."""
    for name in fields:
        value = getattr(obj, name, None)
        if value:
            return str(value)
    return str(obj)


def device_ref(device: object | None) -> tuple[str | None, int | None]:
    """Return (container node id, site id) for a plain ``device`` FK target (or ``(None, None)``)."""
    if device is None:
        return None, None
    return nid("dev", device.pk), getattr(device, "site_id", None)


def dual_host_ref(obj: object) -> tuple[str | None, int | None]:
    """Return (container node id, site id) for an object anchored by the ``host_device`` /
    ``host_vm`` pair (reticulum / meshcore nodes may sit on a device XOR a VM, or neither)."""
    if getattr(obj, "host_device_id", None):
        return nid("dev", obj.host_device_id), getattr(obj.host_device, "site_id", None)
    if getattr(obj, "host_vm_id", None):
        return nid("vm", obj.host_vm_id), vm_site_id(obj.host_vm)
    return None, None


def dual_host_in_scope(scope: Scope, obj: object) -> bool:
    """Scope membership for a ``host_device`` / ``host_vm`` anchored object."""
    if scope.mode == "all":
        return True
    if getattr(obj, "host_device_id", None):
        return scope.includes_device(obj.host_device_id, getattr(obj.host_device, "site_id", None))
    if getattr(obj, "host_vm_id", None):
        return scope.includes_vm(obj.host_vm_id, vm_site_id(obj.host_vm))
    return False
