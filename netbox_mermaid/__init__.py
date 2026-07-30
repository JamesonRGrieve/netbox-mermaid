# SPDX-License-Identifier: AGPL-3.0-or-later
"""netbox-mermaid: a **meta / visualization** NetBox 4.6 plugin that introspects the entire NetBox
source-of-truth and renders it two ways — one readable, well-structured **Mermaid** diagram, and an
exhaustive **SoT report** (markdown / json / toon) — both in the UI and as REST APIs.

**No hard dependencies.** ``required_plugins`` is empty: the plugin OPTIONALLY consumes every
in-house plugin. The **diagram** has one guarded collector per source (core + services, host-roles,
database, webserver, wordpress, ai, pki, email, federation, cloudflare, lb-acl, pf, dhcp, data-link,
wireguard, reticulum, meshcore, zfs, guests); a per-collector ``django.apps.apps.is_installed(...)``
guard means an absent plugin is gracefully skipped, never an error. The **report** is fully generic —
it walks every model of every installed ``netbox_*`` plugin (plus the core apps) automatically, so a
new plugin needs no code. It has **no models** of its own: it reads existing objects and emits views.
"""

from netbox.plugins import PluginConfig

__version__ = "0.1.0"


class NetBoxMermaidConfig(PluginConfig):
    name = "netbox_mermaid"
    verbose_name = "NetBox Mermaid"
    description = "Introspect the whole NetBox SoT: render it as a Mermaid diagram (with a public-safe sanitize mode) and export it as an exhaustive report in markdown / json / toon (UI + API)"
    version = __version__
    author = "Jameson"
    base_url = "mermaid"
    min_version = "4.6.0"
    max_version = "4.6.99"
    # Every in-house plugin is an OPTIONAL source — the collectors guard on apps.is_installed(),
    # so nothing here is a hard dependency.
    required_plugins: list[str] = []


config = NetBoxMermaidConfig
