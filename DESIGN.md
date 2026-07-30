<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->
# netbox-mermaid — Design

## 0. Purpose

Turn the whole NetBox source-of-truth into two complementary views:

1. a **readable, well-structured Mermaid diagram** — a curated `flowchart TD` of the topologically
   meaningful nodes/edges (Section 1–6); and
2. an **exhaustive SoT report** — every model of every relevant app, all fields, in **markdown /
   json / toon** (Section 8).

The two are deliberately different in altitude: the diagram omits per-row detail *for brevity*
(individual firewall rules, DHCP options, ZFS datasets, kernel tunables, SMART snapshots…); the
report captures **all** of it. Both are rendered in the UI and served over REST.

This is a **meta / visualization** plugin: it owns **no models**, defines **no migrations**, and
stores **no data**. It *reads* the core objects and every in-house plugin's objects and *emits* the
diagram + report.

## 1. Render pipeline

```
   Scope (all | site | device | vm)
          │
          ▼
   collectors/registry.collect_all(scope)
          │   each Collector.safe_collect() — guarded by apps.is_installed(app_label)
          │   → typed Node(id,label,kind,parent,raw_attrs) + Edge(src,dst,label)
          ▼
   (optional) sanitizer.Sanitizer().sanitize(nodes, edges)   # public-safe redaction
          │
          ▼
   builder.render(nodes, edges)  → Diagram(mermaid, node_count, edge_count, sanitized)
          │
          ▼
   views.DiagramView (UI, vendored mermaid.js)  /  api.DiagramAPIView (JSON)
```

`builder.build_diagram(scope, sanitize)` is the single orchestrator both the view and the API call.

## 2. Collectors — the extensibility point

One module per source under `collectors/`, each a `Collector` subclass:

| Collector | app_label | Emits |
|-----------|-----------|-------|
| `CoreCollector` | *(always on)* | Site (container) → Device / VM → Tenant edges |
| `ServicesCollector` | `netbox_services` | ServiceInstance (under host); HAMirror + Integration edges |
| `HostRoleCollector` | `netbox_services` | HostRole (catalog) + HostRoleAssignment (under host) → `role` edge |
| `DatabaseCollector` | `netbox_database` | DatabaseServer (under host) → Database / DBUser; grant edges; Galera / Postgres cluster membership |
| `WebServerCollector` | `netbox_webserver` | WebServer (under host) → VirtualHost / PHP-FPM pool; service edge |
| `WordPressCollector` | `netbox_wordpress` | WordPressSite (under host) → plugins/themes; DB / db-user / service / cache edges |
| `AiCollector` | `netbox_ai` | ModelCatalog → ModelVariant; GpuDevice (under host); InferenceDeployment (under service) → variant/GPU; GatewayRoute → deployment targets |
| `PkiCollector` | `netbox_pki` | CA (container) → ACME account / Certificate; cert→service "secures" edges |
| `EmailCollector` | `netbox_email` | MailDomain (under service) → Mailbox / Alias; MailRelay |
| `FederationCollector` | `netbox_federation` | FederationRealm (under service) → FederationPeer |
| `CloudflareCollector` | `netbox_cloudflare` | Tunnel → Ingress / Record; LoadBalancer → Pool → Origin; Pool → Monitor |
| `LbAclCollector` | `netbox_load_balancing_acl` | ACL / RoutingRule / Certificate grouped under a synthetic Listener container |
| `PfCollector` | `netbox_pf` | Gateway / GatewayGroup (under host) + group→gateway tier edges; Alias |
| `DhcpCollector` | `netbox_dhcp` | DHCPScope / v6 subnet / v6 peer (under host) |
| `DataLinkCollector` | `netbox_data_link` | STP / LLDP / DHCP-snooping config (under host) |
| `WireGuardCollector` | `netbox_wireguard` | WireGuardTunnel (under host) → WireGuardPeer |
| `ReticulumCollector` | `netbox_reticulum` | ReticulumNode (under host, else network) → `network` edge |
| `MeshCoreCollector` | `netbox_meshcore` | MeshNode (under host, else network) + MeshLink edges |
| `ZfsCollector` | `netbox_zfs` | ZFSPool (under host) → ZFSVdev |
| `GuestsCollector` | `netbox_guests` | GuestDevice / GuestMount (under VM) |

**Diagram-omitted, report-only plugins.** A few sources add no useful *topology* and would only
clutter the flowchart — they are covered exhaustively by the report instead: `netbox_fs` /
`netbox_smart` (per-partition + SMART inventory, anchored via a `netbox_inventory.Asset` rather than
a device) and `netbox_system_services` (per-device SNMP/NTP/syslog/DNS/tunable config). The report is
generic, so they appear there automatically with zero extra code.

**Graceful skip.** `Collector.available()` returns `False` when `apps.is_installed(app_label)` is
false; `safe_collect()` also swallows an import/query error from a present-but-incompatible plugin,
returning nothing rather than sinking the whole diagram. Models are imported **inside** `collect()`,
never at module top, so an absent plugin never breaks package import.

**Consistent id scheme.** Every node id is `nid(prefix, pk)` = `"<prefix>_<pk>"`. Cross-plugin edges
reconstruct a peer's id from the same `(prefix, pk)` pair **without importing the peer collector**
(e.g. WordPress builds `db_<id>` for its `database_id`). If the owning plugin is absent, the target
node never exists and the builder **drops the dangling edge** — so cross-links are safe by
construction.

**Add a collector = one file.** Subclass `Collector`, set `app_label`, yield `Node`/`Edge`, and
append the instance to `COLLECTORS` in `registry.py`. Nothing else changes.

### Cross-links realized (from the live plugin schemas)

- WordPressSite → `database` / `db_user` (netbox-database), `service_instance` / `object_cache_instance`
  (netbox-services) — labelled edges `db` / `db user` / `service` / `cache`.
- PkiCertificate → `service_instance` — edge `secures`; Certificate nests under its issuing CA.
- DatabaseServer → host (device XOR VM, nesting) + `service_instance` (edge `service`); Galera /
  Postgres membership is a `GaleraNode.server` / `PostgresClusterNode.server` edge to the cluster.
- HAMirror `mirror → primary` — edge `HA mirror`. Integration `consumer → provider`.
- FederationPeer nests under its `realm`; MailDomain nests under its serving `service_instance`.
- **Not a relational link:** `VirtualHost.cert_ref` is a **path string**, not an FK to a
  PkiCertificate — so no cert↔vhost cross-edge is emitted; the ref is carried in `raw_attrs` (which
  the sanitizer drops) rather than fabricated as a relationship.

## 3. Builder — structure + escaping

- **Subgraph nesting.** A node whose id is another node's `parent` renders as a Mermaid `subgraph`;
  leaf nodes render as shaped vertices. This yields the Site → host → instance → detail hierarchy.
- **Kinds.** `classDef` per kind sets colour; leaf nodes get a `class`, container subgraphs a
  `style`. Leaf **shape** is kind-driven (cylinder for databases, stadium for services, hexagon for
  clusters/CAs/tenants, parallelogram for vhosts/certs, rounded for VMs).
- **Escaping.** `escape_label` double-quotes every label and replaces Mermaid-special characters
  with numeric entities (`#` first so later insertions are not re-escaped): `"`→`#34;`, `<`→`#60;`,
  `>`→`#62;`, `|`→`#124;`, `{`/`}`→`#123;`/`#125;`, newlines→`<br/>`. Output parses cleanly.
- **Determinism.** Roots, children, and edges are sorted, so identical input yields byte-identical
  Mermaid — important for the sanitizer's determinism guarantee and for stable tests.
- The only text that reaches the rendered Mermaid is node **labels** and edge **labels**;
  `raw_attrs` are never emitted (reserved for future tooltips) and are dropped entirely on sanitize.

## 4. Sanitizer — threat model = "safe to share publicly"

`sanitize=True` transforms `(nodes, edges)` **before** render so the diagram may be posted publicly
while preserving structure, kinds, and relationships. Guarantees:

- **Leaks nothing identifying.** Real hostnames/FQDNs/object names → generic per-kind labels
  ("Database 1", "Web Host 2"); NetBox pks → stable synthetic ids (`DB1`, `H2`); IPs/CIDRs → `«ip»`;
  e-mails → `«email»`; OpenBao/secret/credential refs → `«secret»`; tenant/customer/org names →
  "Tenant A/B"; `raw_attrs` (serials, asset tags, secret refs, internal domains) → dropped.
- **Deterministic per run.** Nodes are processed in sorted-id order; the same real value always maps
  to the same generic label, so a hostname reused in a node label and an edge label redacts to the
  **same** token and cross-links stay coherent.
- **Structure intact.** Node and edge **counts are preserved**; parent nesting is remapped to the
  synthetic ids; only endpoints that fall outside the graph drop an edge.

## 5. UI + CSP

NetBox ships a strict Content-Security-Policy that blocks external hosts and inline scripts, so
`mermaid.min.js` is **vendored locally** into `static/netbox_mermaid/` and the render/controls logic
lives in a **static** `diagram-init.js` (no inline JS, no CDN). The init script reads the Mermaid
source from the page, renders it client-side, wires the copy/toggle buttons, and — if the vendored
asset is a stub or fails to load — **degrades** to showing the copyable source `<pre>`. The template
+ both static assets ship in the wheel via `package-data`.

## 6. Scope

`Scope` (`all` | `site` | `device` | `vm` + id) keeps large deployments readable. Host-anchored
collectors (core, services, database, webserver, wordpress) filter their objects to the window; the
non-host-anchored collectors (pki, email, federation) populate only in whole-SoT (`all`) scope,
since their relationship to a host is indirect (via a service instance).

## 7. The SoT report (markdown / json / toon)

Where the diagram is curated, the **report** is exhaustive and **fully generic** — it never needs
editing when a plugin is added. Pipeline (mirrors the diagram's):

```
   report/introspect.build_report(include_empty=False)
          │   discover_apps(): core apps (tenancy/dcim/ipam/vpn/virtualization/circuits/wireless)
          │                    + every installed `netbox_*` app  (minus netbox_mermaid itself)
          │   per model: serialise EVERY concrete field of EVERY object (FKs → related __str__,
          │              generic-FKs resolved, m2m + tags as lists, JSON fields kept)
          ▼
   one JSON-safe dict {report, generated, netbox_version, summary, sections:[{app, models:[…]}]}
          │
          ▼
   report/render.render_report(data, fmt) → (content, content_type, filename)
          ├─ markdown → headed doc: summary, a Contents index, one table per model
          ├─ json     → json.dumps (structured, native values preserved)
          └─ toon     → report/toon.encode (see below)
          │
          ▼
   views.ReportView (UI, ?format=, ?download=1)  /  api.ReportAPIView (raw, content-typed)
```

- **Generic introspection** (`report/introspect.py`). Models come from `apps.get_app_config(label)
  .get_models()`; fields from `model._meta.concrete_fields` (skipping `_`-prefixed cache columns)
  plus `many_to_many` + taggit `tags`. FK/O2O render as the related object's `__str__` (with a
  `select_related` to avoid N+1); GenericForeignKeys are resolved from `_meta.private_fields`. Every
  value is coerced JSON-safe (`Decimal`/date/`IP`/`UUID` → str; dict/list recurse). A broken model
  degrades to an `error` marker rather than 500-ing the report. Empty models are hidden unless
  `?include_empty=1`.
- **Secret hygiene.** A field whose name matches a credential hint (`password`, `secret`, `token`,
  `private_key`, `psk`, `api_key`, `credential`, …) is redacted to `«redacted»` — the key stays so
  the schema is legible. OpenBao **path** references are *pointers, not secrets*, and are kept.
- **The report is an internal artifact** — it is deliberately complete, the opposite of the
  diagram's public-safe `sanitize`. To share externally, use the diagram's sanitize mode, not the
  report.
- **TOON** (`report/toon.py`) is a standalone, token-cheap encoder: YAML-style `key: value` nesting,
  arrays declare their length inline (`tags[3]: a,b,c`), and a *uniform* array of flat objects
  renders as a **table** — one header of field names, then one comma-separated row per object — so
  each field name is written once instead of once per element (the report's `objects[]` lists hit
  this path). Non-uniform/nested arrays fall back to `-` list items. It has no NetBox/Django imports
  and is fully unit-tested (`tests/test_toon.py`).

## 8. Verification owed (cannot run offline — no NetBox env in the build host)

`python -m py_compile` passes on every module. Owed against a live, pinned **NetBox 4.6**:

- `python /opt/netbox/app/netbox/manage.py test netbox_mermaid --keepdb -v2` green (builder over a
  real Site/Device/VM graph; sanitizer leak/determinism/count guarantees + kind-id uniqueness;
  report structure + markdown/json/toon render; diagram + report API 200s; toon encoder units).
- A **live UI render**: confirm the vendored `mermaid.min.js` draws the flowchart under NetBox's CSP
  (it exposes `globalThis.mermaid`), the scope/sanitize controls round-trip, and copy works; and that
  the **SoT Report** page renders + downloads in all three formats.
- Re-confirm the optional-source field names against each deployed sibling wheel (they are read
  through guarded imports, so a rename degrades to a skipped source, not a crash) — see the field
  map that drove the collectors. The **report** is field-name-agnostic (generic introspection), so it
  is immune to plugin field renames.

Open items are tracked in `todo.json`.
