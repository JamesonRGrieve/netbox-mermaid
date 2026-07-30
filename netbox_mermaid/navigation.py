# SPDX-License-Identifier: AGPL-3.0-or-later
from netbox.plugins import PluginMenu, PluginMenuItem

menu = PluginMenu(
    label="SoT Diagram",
    groups=(
        (
            "Visualization",
            (
                PluginMenuItem(
                    link="plugins:netbox_mermaid:diagram",
                    link_text="SoT Diagram",
                ),
                PluginMenuItem(
                    link="plugins:netbox_mermaid:report",
                    link_text="SoT Report",
                ),
            ),
        ),
    ),
    icon_class="mdi mdi-sitemap",
)
