# SPDX-License-Identifier: AGPL-3.0-or-later
"""netbox-ai collector: the inference topology — ModelCatalog (container) → ModelVariant; GpuDevices
nested under their host device; InferenceDeployments (hung under the serving ServiceInstance) with
their variant + GPU edges; and GatewayRoutes with ordered target edges to deployments.

GpuDevice is host-anchored (a real ``device`` FK) and honours scope; the catalog / deployment /
route layer is service- and account-shaped and populates only in whole-SoT (``all``) scope.
Optional — skipped when the plugin is absent.
"""

from __future__ import annotations

from .base import Collector, Edge, Node, Scope, device_ref, display, nid


class AiCollector(Collector):
    app_label = "netbox_ai"
    kind = "aideploy"

    def collect(self, scope: Scope) -> tuple[list[Node], list[Edge]]:
        from netbox_ai.models import (
            GatewayRoute,
            GatewayRouteTarget,
            GpuDevice,
            InferenceDeployment,
            ModelCatalog,
            ModelVariant,
        )

        nodes: list[Node] = []
        edges: list[Edge] = []

        for gpu in GpuDevice.objects.select_related("device", "device__site"):
            host_id, site_id = device_ref(gpu.device)
            if not scope.includes_device(gpu.device_id, site_id):
                continue
            nodes.append(Node(nid("gpu", gpu.pk), f"GPU{gpu.index}", "gpu", parent=host_id))

        if scope.mode != "all":
            return nodes, edges

        for catalog in ModelCatalog.objects.all():
            nodes.append(
                Node(nid("aicatalog", catalog.pk), display(catalog, "display_name", "name"), "aicatalog")
            )
        for variant in ModelVariant.objects.all():
            nodes.append(
                Node(
                    nid("aivariant", variant.pk),
                    display(variant, "quant"),
                    "aivariant",
                    parent=nid("aicatalog", variant.model_id),
                )
            )
        for dep in InferenceDeployment.objects.prefetch_related("gpus"):
            parent = nid("svc", dep.service_instance_id) if dep.service_instance_id else None
            nodes.append(
                Node(nid("aideploy", dep.pk), display(dep, "served_model_name"), "aideploy", parent=parent)
            )
            if dep.variant_id:
                edges.append(Edge(nid("aideploy", dep.pk), nid("aivariant", dep.variant_id), "model"))
            for gpu in dep.gpus.all():
                edges.append(Edge(nid("aideploy", dep.pk), nid("gpu", gpu.pk), "gpu"))
        for route in GatewayRoute.objects.all():
            parent = nid("svc", route.service_instance_id) if route.service_instance_id else None
            nodes.append(
                Node(nid("airoute", route.pk), display(route, "public_name"), "airoute", parent=parent)
            )
        for target in GatewayRouteTarget.objects.all():
            edges.append(
                Edge(nid("airoute", target.route_id), nid("aideploy", target.deployment_id), "target")
            )

        return nodes, edges
