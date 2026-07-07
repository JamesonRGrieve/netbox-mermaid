# SPDX-License-Identifier: AGPL-3.0-or-later
"""REST surface: a single read-only endpoint returning the Mermaid source string + counts.

This is a plain DRF ``APIView`` (there is no model to expose as a ``ModelViewSet``). Query params
``scope`` / ``site`` / ``device`` / ``vm`` narrow the graph; ``sanitize=true`` applies the
public-safe redaction.
"""

from __future__ import annotations

from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from ..builder import build_diagram
from ..collectors.base import Scope

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
