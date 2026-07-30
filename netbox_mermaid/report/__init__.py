# SPDX-License-Identifier: AGPL-3.0-or-later
"""SoT report subsystem: exhaustive, format-flexible export of the entire NetBox source-of-truth.

Pipeline mirrors the diagram's: :func:`build_report` introspects every model of every relevant app
into one JSON-safe dict, then :func:`render_report` encodes it as markdown / json / toon. Unlike the
diagram it is fully generic — no per-plugin code — so it always covers the whole SoT, including the
detail the diagram omits for brevity.
"""

from __future__ import annotations

from .introspect import build_report
from .render import DEFAULT_FORMAT, FORMATS, normalize_format, render_report

__all__ = [
    "DEFAULT_FORMAT",
    "FORMATS",
    "build_report",
    "normalize_format",
    "render_report",
]
