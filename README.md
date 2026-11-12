<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->
# netbox-mermaid

A **meta / visualization** NetBox 4.6 plugin: it introspects the **entire NetBox source-of-truth**
and renders it two ways — one readable, well-structured **Mermaid** `flowchart`, and an exhaustive
**SoT report** in **markdown / json / toon** — in the NetBox UI and as REST APIs. It has **no models
of its own**; it reads what is already in NetBox.

The two views sit at different altitudes on purpose: the **diagram** is curated (only the
topologically meaningful nodes/edges — it omits per-row detail for readability), while the **report**
is exhaustive (every model, every field, everything the diagram leaves out).

## No hard dependencies — every plugin is an optional source

`PluginConfig.required_plugins = []`. The **diagram** OPTIONALLY consumes every in-house plugin via
one **collector** each — `netbox-services` (service instances + host-roles), `-database`,
`-webserver`, `-wordpress`, `-ai`, `-pki`, `-email`, `-federation`, `-cloudflare`,
`-load-balancing-acl`, `-pf`, `-dhcp`, `-data-link`, `-wireguard`, `-reticulum`, `-meshcore`, `-zfs`,
`-guests`. Each is guarded by `django.apps.apps.is_installed(<app_label>)` + a guarded import: an
absent plugin is **silently skipped**, never an error. Installed with none of them, it still renders
the core-only diagram (Sites → Devices / VMs → Tenants).

The **report** needs no such wiring — it introspects **generically**, so every installed `netbox_*`
plugin (and the core apps) appears automatically, no code per plugin.

Install the whole surface with the extra:

```bash
uv pip install --python /opt/netbox/venv/bin/python "netbox-mermaid[all]"
```

## View it

- **UI:** *Plugins → SoT Diagram → SoT Diagram*. Controls: a **view** selector (`Services` /
  `Physical` / `Logical` / `Everything`), a **scope** selector (`Whole SoT` / `Site` / `Device` /
  `VM` + the matching id), a **tenant** filter (id or slug), a **"Sanitize (safe to share)"**
  toggle, a **"Copy Mermaid source"** button, and a **"Toggle source"** button. The diagram is drawn
  client-side by a **locally vendored** `mermaid.min.js` (NetBox's strict CSP blocks CDNs) via a
  static, CSP-safe init script — no inline JS. If the vendored asset is a stub, the page degrades to
  showing the copyable Mermaid **source**.
- **API:** `GET /api/plugins/mermaid/diagram/` →

  ```json
  { "mermaid": "flowchart TD\n…", "node_count": 42, "edge_count": 37, "sanitized": false,
    "view": "services", "tenant": null }
  ```

  Query params: `?view=services|physical|logical|all`, `?scope=all|site|device|vm`, `?site=<id>`,
  `?device=<id>`, `?vm=<id>`, `?tenant=<id or slug>`, `?sanitize=true`.

### Views

| `view` | Draws |
|---|---|
| `services` (default) | the service/application layer, one box per host holding what runs on it (labelled `catalog` over `hostname`), each guest inside the hypervisor running it: instances, databases, web servers, certs, mail, LB, firewall, VPN, storage. The **request path** is drawn: each DNS zone (netbox-dns, with its netbox-cloudflare records) groups its records by target (`A 172.23.0.254` over `@ · auth · erp …`) and arrows to the host owning the address; each HAProxy (netbox-load-balancing) sits in its firewall's box with a line to every guest it routes to, labelled with the hostnames and backend port. Hosts, racks and rooms with nothing drawn inside are left out |
| `physical` | devices in their rack/room (`Location`) boxes, each guest **inside** the hypervisor running it (its device, else its cluster's only device; a guest on a multi-host cluster gets `can run on` arrows instead), and **one plain line per cabled device pair** labelled with every port pair on it (`nic0 ↔ 1/46`, one per line) |
| `logical` | a **network** node per VLAN (`VLAN <vid> <name>` over its prefix(es) and `gw <IP> · <firewall>`; a VLAN-less prefix of the tenant/site window is a network too), a **host** node per device/VM addressed in one (name over its addresses), and **a line from each network to each host on it**. Addresses match prefixes in their **own VRF** only, longest prefix first |
| `all` | every layer, drawn left → right: DNS zones and networks on the left, each host (guests inside their hypervisor) lined to its networks with the address on the line, cabling to the right |

The tenant → site → location → host spine is drawn in every view. A **tenant is a bounding box**
around its sites, never an edge target.

### Layout

Diagrams use straight connectors and compact spacing (an `%%{init}%%` directive ahead of the
`flowchart` line). A container with more than six independent children (single boxes, or clusters
of boxes joined only to each other, such as a network and the hosts on it) lays them out as a grid
of columns instead of one very wide row, and orders each cluster to keep its lines from crossing.
Siblings sort by kind, then naturally (`VLAN 4` before `VLAN 60`).

### Tenant filter

`tenant=<id or slug>` combines with any scope and keeps that tenant's devices and VMs, plus every
device that hosts one of its VMs (the VM's device, or its cluster's devices); in the logical view it
also shows the tenant's VLANs and VLAN-less prefixes. Service-layer objects with no host (an AI model
catalog, a CA, a Cloudflare zone) are kept only when they nest in, or are one edge from, something in
the window. An unknown slug yields an empty diagram, never the whole SoT.

## The SoT report — export everything

The report is the exhaustive counterpart to the diagram: **every model of every installed `netbox_*`
plugin plus the core apps (tenancy / dcim / ipam / vpn / virtualization / circuits / wireless)**,
with **all** concrete fields of **all** objects — including the per-row detail the diagram omits for
brevity (firewall rules, DHCP options, ZFS datasets, SMART reports, kernel tunables, …).

- **UI:** *Plugins → SoT Diagram → SoT Report*. Pick a **format** (Markdown / JSON / TOON), optionally
  **Include empty models**, then **Render** or **Download**.
- **API:** `GET /api/plugins/mermaid/report/?format=markdown|json|toon` — returns the raw artifact
  with the matching content-type (`json` returns the structured document natively). Add `&download=1`
  for a file-download disposition, `&include_empty=1` to keep zero-row models.

**Formats.** *Markdown* — a headed document with a Contents index and one table per model. *JSON* —
the structured document (native values). *TOON* ([Token-Oriented Object Notation](https://toonformat.dev))
— a token-cheap encoding where each model's object list becomes a table (field names written once),
ideal for handing the whole SoT to an LLM.

**Secret hygiene + scope.** Credential-valued fields (`password` / `secret` / `token` /
`private_key` / …) are redacted to `«redacted»`; OpenBao *path* references are kept (pointers, not
secrets). The report is **complete by design — an internal artifact**; to share externally, use the
diagram's sanitize mode, not the report.

## Sanitize — safe to share publicly

`sanitize=1` (UI toggle) / `?sanitize=true` (API) applies a redaction pass **before** rendering so
the diagram is safe to post in public (a forum, a blog post) while preserving **structure + kinds +
relationships**. It replaces real hostnames/FQDNs/object names with deterministic generic per-kind
labels ("Database 1", "Web Host 2", "VM 3"), maps NetBox pks to stable synthetic ids, scrubs
IPs/CIDRs (`«ip»`), e-mails (`«email»`), OpenBao/secret refs (`«secret»`), and tenant names
("Tenant A/B"), and drops all extra attributes. Same real value → same generic label, so the
architecture stays coherent; node/edge counts are unchanged.

## Extend it — add a diagram collector

Adding a new **diagram** source is a **one-file drop-in**: write a `Collector` subclass in
`netbox_mermaid/collectors/`, guard it with an `app_label`, yield `Node`/`Edge` records, and append
its instance to `COLLECTORS` in `registry.py`. Give any new node `kind` a colour in `builder` and a
distinct id abbreviation in `sanitizer`. Nothing else changes. The **report** requires no extension —
it already covers every model generically. See **DESIGN.md**.

## Develop / test

Tests run against a **real NetBox test database** (no mocks):

```bash
python /opt/netbox/app/netbox/manage.py test netbox_mermaid --keepdb -v2
```

## License

AGPL-3.0-or-later.
