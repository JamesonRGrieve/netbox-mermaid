# SPDX-License-Identifier: AGPL-3.0-or-later
"""netbox-mermaid: a **meta / visualization** NetBox 4.6 plugin that introspects the entire NetBox
source-of-truth and renders it as one readable, well-structured **Mermaid** diagram — both in the
UI and as a source-string REST API.

**No hard dependencies.** ``required_plugins`` is empty: the plugin OPTIONALLY consumes every
in-house plugin (netbox-services, -database, -wordpress, -webserver, -pki, -email, -federation).
Each source's data is included only if that plugin is installed — a per-collector
``django.apps.apps.is_installed(...)`` guard means an absent plugin is gracefully skipped, never an
error. It has **no models** of its own: it reads existing objects and emits a diagram.
"""

from netbox.plugins import PluginConfig

__version__ = "0.0.1"


class NetBoxMermaidConfig(PluginConfig):
    name = "netbox_mermaid"
    verbose_name = "NetBox Mermaid"
    description = "Introspect the whole NetBox SoT and render it as a Mermaid diagram (UI + API), with a public-safe sanitize mode"
    version = __version__
    author = "Jameson"
    base_url = "mermaid"
    min_version = "4.6.0"
    max_version = "4.6.99"
    # Every in-house plugin is an OPTIONAL source — the collectors guard on apps.is_installed(),
    # so nothing here is a hard dependency.
    required_plugins: list[str] = []


config = NetBoxMermaidConfig
