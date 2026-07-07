# SPDX-License-Identifier: AGPL-3.0-or-later
"""Source collectors: one module per NetBox source, each guarded so an absent plugin is skipped.

The public surface is :func:`netbox_mermaid.collectors.registry.collect_all`; individual collector
classes are the extension point (subclass :class:`base.Collector`, register in ``registry.py``).
"""
