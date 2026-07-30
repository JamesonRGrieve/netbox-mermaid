# SPDX-License-Identifier: AGPL-3.0-or-later
from django.urls import path

from . import views

urlpatterns = [
    path("diagram/", views.DiagramView.as_view(), name="diagram"),
    path("report/", views.ReportView.as_view(), name="report"),
]
