<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->
# netbox-mermaid

A **meta / visualization** NetBox 4.6 plugin: it introspects the **entire NetBox source-of-truth**
and renders it as one readable, well-structured **Mermaid** `flowchart` — in the NetBox UI and as a
source-string REST API. It has **no models of its own**; it reads what is already in NetBox.

## No hard dependencies — every plugin is an optional source

`PluginConfig.required_plugins = []`. The plugin OPTIONALLY consumes every in-house plugin
(`netbox-services`, `-database`, `-wordpress`, `-webserver`, `-pki`, `-email`, `-federation`). Each
source has a **collector** guarded by `django.apps.apps.is_installed(<app_label>)` + a guarded
import: an absent plugin is **silently skipped**, never an error. Installed with none of them, it
still renders the core-only diagram (Sites → Devices / VMs → Tenants).

Install the whole surface with the extra:

```bash
uv pip install --python /opt/netbox/venv/bin/python "netbox-mermaid[all]"
```

## View it

- **UI:** *Plugins → SoT Diagram → SoT Diagram*. Controls: a **scope** selector
  (`Whole SoT` / `Site` / `Device` / `VM` + the matching id), a **"Sanitize (safe to share)"**
  toggle, a **"Copy Mermaid source"** button, and a **"Toggle source"** button. The diagram is drawn
  client-side by a **locally vendored** `mermaid.min.js` (NetBox's strict CSP blocks CDNs) via a
  static, CSP-safe init script — no inline JS. If the vendored asset is a stub, the page degrades to
  showing the copyable Mermaid **source**.
- **API:** `GET /api/plugins/mermaid/diagram/` →

  ```json
  { "mermaid": "flowchart TD\n…", "node_count": 42, "edge_count": 37, "sanitized": false }
  ```

  Query params: `?scope=all|site|device|vm`, `?site=<id>`, `?device=<id>`, `?vm=<id>`,
  `?sanitize=true`.

## Sanitize — safe to share publicly

`sanitize=1` (UI toggle) / `?sanitize=true` (API) applies a redaction pass **before** rendering so
the diagram is safe to post in public (a forum, a blog post) while preserving **structure + kinds +
relationships**. It replaces real hostnames/FQDNs/object names with deterministic generic per-kind
labels ("Database 1", "Web Host 2", "VM 3"), maps NetBox pks to stable synthetic ids, scrubs
IPs/CIDRs (`«ip»`), e-mails (`«email»`), OpenBao/secret refs (`«secret»`), and tenant names
("Tenant A/B"), and drops all extra attributes. Same real value → same generic label, so the
architecture stays coherent; node/edge counts are unchanged.

## Extend it — add a collector

Adding a new source is a **one-file drop-in**: write a `Collector` subclass in
`netbox_mermaid/collectors/`, guard it with an `app_label`, yield `Node`/`Edge` records, and append
its instance to `COLLECTORS` in `registry.py`. Nothing else changes. See **DESIGN.md**.

## Develop / test

Tests run against a **real NetBox test database** (no mocks):

```bash
python /opt/netbox/app/netbox/manage.py test netbox_mermaid --keepdb -v2
```

## License

AGPL-3.0-or-later.
