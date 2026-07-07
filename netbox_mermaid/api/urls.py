# SPDX-License-Identifier: AGPL-3.0-or-later
from django.urls import path

from . import views

app_name = "netbox_mermaid"

urlpatterns = [
    path("diagram/", views.DiagramAPIView.as_view(), name="diagram"),
]
