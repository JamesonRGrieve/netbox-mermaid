# netbox-mermaid — Agent Operating Guide

Adapted from the sibling `../netbox-database` plugin (same engineering + test discipline),
re-targeted to a **meta / visualization** role. Unlike its lineage, this plugin has **no models,
no migrations, no forms/tables/filtersets** — instead a **collectors** package, a **builder**, a
**sanitizer**, a UI **view + template**, and a REST **APIView**.

`netbox-mermaid` is an **AGPL-3.0** NetBox 4.6 plugin: it introspects the **entire NetBox
source-of-truth** and renders it as one readable, well-structured **Mermaid** `flowchart` — in the
UI and as a source-string REST API. See **DESIGN.md** for the render pipeline, the collector
registry, the builder, the sanitizer threat-model, and verification owed.

**No hard dependencies — introspection design.** `required_plugins = []`. Every in-house plugin is
an OPTIONAL source: one collector per source, each guarded by `apps.is_installed(<app_label>)` + a
guarded import, so an absent plugin is a **graceful skip**, never an error. Installed alone, the
plugin renders the core-only diagram.

**Sanitize = "safe to share publicly."** The `sanitize=True` transform redacts hostnames, IPs,
e-mails, secret refs, tenant names, and pks to deterministic generic per-kind labels **before**
render, preserving structure + kinds + relationships and node/edge counts. It is the load-bearing
safety feature — never weaken it.

---

## Key Directives / Rules

### DO, ALWAYS:
- Keep the plugin **model-free**. If you find yourself adding `models.py` / a migration, stop — this
  plugin reads existing objects, it does not own data.
- Add a new source as a **one-file drop-in**: a `Collector` subclass in `collectors/`, guarded by
  `app_label`, registered in `registry.py`. Import the source's models **inside** `collect()`, never
  at module top.
- Reconstruct cross-plugin node ids via `nid(prefix, pk)` — never import a peer collector. A dangling
  edge (owning plugin absent) is dropped by the builder; that is the intended graceful behavior.
- Escape every label through `builder.escape_label`; emit only labels into Mermaid, never `raw_attrs`.
- Any time you modify a source file, extend its test under `netbox_mermaid/tests/` **without mocks**
  so `manage.py test netbox_mermaid` discovers it, and update co-located `.md`.
- **SPDX header on every source file**: `# SPDX-License-Identifier: AGPL-3.0-or-later`.

### DO NOT, EVER, UNDER ANY CIRCUMSTANCE:
- Add a hard dependency on any in-house plugin, or import a plugin's models at module top level.
- Weaken the sanitizer: never let a real hostname, IP, e-mail, secret ref, tenant name, or pk reach
  the sanitized output; never break its determinism or its count-preservation guarantee.
- Load `mermaid.min.js` from a CDN or add inline `<script>`/`onclick` — NetBox's CSP forbids it;
  vendor the asset locally and keep JS in the static init file.
- Make assumptions, or answer with "is likely" / "probably" / "might be".
- Use frame-local / thread-local state instead of passing data via parameters.
- Skip a failing test; keep a broken path as a fallback; re-implement a function in a second place.
- **Mock the database, the ORM, or the NetBox API test client.** Tests run against a **real test
  database** with real `dcim.Device` / `virtualization.VirtualMachine` (+ sibling rows when installed).

### Python / Django Guidelines:
- Package-relative imports inside `netbox_mermaid` (`from .builder import build_diagram`); core/
  sibling models use the real path **inside** the collector method (`from dcim.models import Device`).
- `from __future__ import annotations`; type every signature; `X | None` over `Optional`.

---

## Architecture (NetBox 4.6 plugin, model-free)

| File | Responsibility |
|------|----------------|
| `__init__.py` | `PluginConfig` — name `netbox_mermaid`, `base_url='mermaid'`, min/max 4.6, `required_plugins=[]` |
| `collectors/base.py` | `Node` / `Edge` / `Scope` dataclasses, `nid()` id scheme, `Collector` base + `safe_collect` guard, host-resolution helpers |
| `collectors/core.py` | always-on core: Site / Device / VM / Tenant |
| `collectors/{services,database,webserver,wordpress,pki,email,federation}.py` | one optional source each |
| `collectors/registry.py` | `COLLECTORS` list + `collect_all(scope)` — the extension point |
| `builder.py` | assemble → Mermaid `flowchart TD` (subgraph nesting, classDef/shape, escaping); `build_diagram(scope, sanitize)` orchestrator |
| `sanitizer.py` | `Sanitizer` — public-safe deterministic redaction |
| `views.py`, `urls.py`, `navigation.py` | UI page (`PluginMenu` "SoT Diagram") |
| `templates/netbox_mermaid/diagram.html` | detail page (extends `base/layout.html`): scope + sanitize controls, copy/toggle, vendored render |
| `static/netbox_mermaid/mermaid.min.js`, `diagram-init.js` | vendored renderer + CSP-safe init |
| `api/views.py`, `api/urls.py` | DRF `APIView` → `{mermaid, node_count, edge_count, sanitized}` |

---

## Testing (NO MOCKS — real DB, NetBox test framework)

- `tests/test_builder.py`: real Site/Device/VM graph → `flowchart` header, node ids/labels, subgraph
  nesting, label escaping; a plugin assertion guarded behind `apps.is_installed(...)`.
- `tests/test_sanitizer.py`: seeded graph → asserts **none** of the real hostnames/IPs/secret-refs
  survive, the same real value maps to the same generic label (determinism), and node/edge **counts**
  are preserved. Pure (`SimpleTestCase`).
- `tests/test_api.py`: `GET /api/plugins/mermaid/diagram/` (+ `?sanitize=true`) → 200, non-empty
  `mermaid`, integer counts, `sanitized` echo.
- **Run**: `python /opt/netbox/app/netbox/manage.py test netbox_mermaid --keepdb -v2`.
- **Verification owed (no NetBox env in the build host):** the full test run, plus a **live UI
  render** confirming the vendored `mermaid.min.js` draws under NetBox's CSP. `py_compile` passes on
  every module today. Never skip a failing test — fix the root cause.

---

## Licensing
- **AGPL-3.0-or-later** (workspace production-IaC standard). SPDX header in every file.
