# SPDX-License-Identifier: AGPL-3.0-or-later
"""REST surface: read-only endpoints for the diagram and the whole-SoT report.

These are plain DRF ``APIView``\\ s (there is no model to expose as a ``ModelViewSet``).

* ``GET /api/plugins/mermaid/diagram/`` — the Mermaid source string + counts. Query params
  ``scope`` / ``site`` / ``device`` / ``vm`` narrow the graph; ``sanitize=true`` redacts.
* ``GET /api/plugins/mermaid/report/`` — the entire source-of-truth. ``format=markdown|json|toon``
  (default markdown). ``json`` returns the structured document natively; ``markdown``/``toon`` return
  the raw text with the matching content-type. ``download=1`` adds a file-download disposition;
  ``include_empty=1`` keeps zero-row models.
"""

from __future__ import annotations

from django.http import HttpResponse
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from ..builder import build_diagram
from ..collectors.base import Scope
from ..report import build_report, normalize_format, render_report

_TRUE = {"1", "true", "yes", "on"}


class DiagramAPIView(APIView):
    """``GET /api/plugins/mermaid/diagram/`` → ``{mermaid, node_count, edge_count, sanitized}``."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        sanitize = str(request.query_params.get("sanitize", "")).lower() in _TRUE
        scope = Scope.from_params(request.query_params)
        diagram = build_diagram(scope=scope, sanitize=sanitize)
        return Response(
            {
                "mermaid": diagram.mermaid,
                "node_count": diagram.node_count,
                "edge_count": diagram.edge_count,
                "sanitized": diagram.sanitized,
            }
        )


class ReportAPIView(APIView):
    """``GET /api/plugins/mermaid/report/`` → the whole SoT in the requested format."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> HttpResponse:
        fmt = normalize_format(request.query_params.get("format"))
        include_empty = str(request.query_params.get("include_empty", "")).lower() in _TRUE
        download = str(request.query_params.get("download", "")).lower() in _TRUE
        data = build_report(include_empty=include_empty)
        content, content_type, filename = render_report(data, fmt)
        response = HttpResponse(content, content_type=content_type)
        if download:
            response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response
