# SPDX-License-Identifier: AGPL-3.0-or-later
"""UI view: the SoT diagram page. Renders the Mermaid source (built from the current scope +
sanitize toggle) into a template that draws it client-side with the locally vendored mermaid.js.
"""

from __future__ import annotations

from django.shortcuts import render
from django.views.generic import View

from .builder import build_diagram
from .collectors.base import Scope

_TRUE = {"1", "true", "yes", "on"}


class DiagramView(View):
    """Whole-SoT (or scoped) Mermaid diagram. GET params: ``scope`` / ``site`` / ``device`` /
    ``vm`` narrow the graph; ``sanitize=1`` applies the public-safe redaction."""

    template_name = "netbox_mermaid/diagram.html"

    def get(self, request):
        sanitize = request.GET.get("sanitize", "").lower() in _TRUE
        scope = Scope.from_params(request.GET)
        diagram = build_diagram(scope=scope, sanitize=sanitize)
        context = {
            "mermaid_source": diagram.mermaid,
            "node_count": diagram.node_count,
            "edge_count": diagram.edge_count,
            "sanitized": diagram.sanitized,
            "scope": scope,
        }
        return render(request, self.template_name, context)
