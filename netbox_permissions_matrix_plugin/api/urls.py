from django.urls import path
from rest_framework.routers import APIRootView

from . import views


class PermissionsMatrixRootView(APIRootView):
    """The plugin's API root, listed under /api/plugins/ like other plugins' (NetBox looks it up as api-root)."""

    def get_view_name(self):
        return "Permissions Matrix"


ENDPOINTS = {
    "matrix": views.MatrixView,
    "principal": views.PrincipalView,
    "plan": views.PlanView,
    "apply": views.ApplyView,
    "import": views.ImportView,
}

urlpatterns = [
    path("", PermissionsMatrixRootView.as_view(api_root_dict={name: name for name in ENDPOINTS}), name="api-root"),
    *(path(f"{name}/", view.as_view(), name=name) for name, view in ENDPOINTS.items()),
]
