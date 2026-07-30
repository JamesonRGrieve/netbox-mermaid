# SPDX-License-Identifier: AGPL-3.0-or-later
"""UI views.

* :class:`DiagramView` — the SoT diagram page: renders the Mermaid source (built from the current
  scope + sanitize toggle) into a template that draws it client-side with the vendored mermaid.js.
* :class:`ReportView` — the SoT report page: renders the whole source-of-truth in the chosen format
  (markdown / json / toon) with a download button, or streams the raw artifact when ``?download=1``.
"""

from __future__ import annotations

from django.http import HttpResponse
from django.shortcuts import render
from django.views.generic import View

from .builder import build_diagram
from .collectors.base import Scope
from .report import build_report, normalize_format, render_report

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


class ReportView(View):
    """Whole-SoT export in ``markdown`` | ``json`` | ``toon``. ``?format=`` picks the format;
    ``?download=1`` streams the raw file; ``?include_empty=1`` keeps zero-row models."""

    template_name = "netbox_mermaid/report.html"

    def get(self, request):
        fmt = normalize_format(request.GET.get("format"))
        include_empty = request.GET.get("include_empty", "").lower() in _TRUE
        data = build_report(include_empty=include_empty)
        content, content_type, filename = render_report(data, fmt)

        if request.GET.get("download", "").lower() in _TRUE:
            response = HttpResponse(content, content_type=content_type)
            response["Content-Disposition"] = f'attachment; filename="{filename}"'
            return response

        summary = data.get("summary", {})
        context = {
            "report_source": content,
            "format": fmt,
            "include_empty": include_empty,
            "summary": summary,
            "generated": data.get("generated"),
            "netbox_version": data.get("netbox_version"),
        }
        return render(request, self.template_name, context)
