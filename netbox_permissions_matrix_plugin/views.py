from django.conf import settings
from django.contrib.auth.mixins import AccessMixin
from django.shortcuts import render
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from django.views import View
from netbox.views import generic
from users.models import Group
from utilities.views import ViewTab, register_model_view

from . import service
from .conf import get_setting
from .version import __version__

API = "plugins-api:netbox_permissions_matrix_plugin-api"


class MatrixAccessMixin(AccessMixin):
    def dispatch(self, request, *args, **kwargs):
        # Anonymous users go to the login page; authenticated users without access get NetBox's 403 page with the
        # reason (service.check_view raises PermissionDenied with a message).
        if not request.user.is_authenticated and settings.LOGIN_REQUIRED:
            return self.handle_no_permission()
        service.check_view(request.user)
        return super().dispatch(request, *args, **kwargs)


def api_urls() -> dict:
    return {name: reverse(f"{API}:{name}") for name in ("matrix", "principal", "plan", "apply")}


class MatrixView(MatrixAccessMixin, View):
    def get(self, request):
        return render(
            request,
            "netbox_permissions_matrix_plugin/matrix.html",
            {
                "action": request.GET.get("action", "view"),
                "can_edit": service.can_edit(request.user),
                "api": api_urls(),
                "show_users": get_setting("show_users_by_default"),
                "pm_version": __version__,
                "who_can_url": reverse("plugins:netbox_permissions_matrix_plugin:who_can", args=["__ot__"]),
            },
        )


class WhoCanView(MatrixAccessMixin, View):
    def get(self, request, object_type):
        context = service.who_can(request.user, object_type)
        context["matrix_url"] = reverse("plugins:netbox_permissions_matrix_plugin:matrix")
        context["pm_version"] = __version__
        return render(request, "netbox_permissions_matrix_plugin/who_can.html", context)


@register_model_view(Group, "permissions_matrix", path="permissions-matrix")
class GroupPermissionsMatrixView(generic.ObjectView):
    """The group's own matrix, as a tab on the group's page."""

    queryset = Group.objects.all()
    template_name = "netbox_permissions_matrix_plugin/principal_tab.html"
    tab = ViewTab(label=_("Permissions Matrix"), permission="users.view_objectpermission", weight=600)

    def get(self, request, *args, **kwargs):
        service.check_view(request.user)
        return super().get(request, *args, **kwargs)

    def get_extra_context(self, request, instance):
        return {
            "principal_key": f"group:{instance.pk}",
            "api": api_urls(),
            "can_edit": service.can_edit(request.user),
            "pm_version": __version__,
            "who_can_url": reverse("plugins:netbox_permissions_matrix_plugin:who_can", args=["__ot__"]),
        }
