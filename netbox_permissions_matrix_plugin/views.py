import datetime
import functools
import hashlib
from pathlib import Path

from django.http import HttpResponse
from django.shortcuts import render
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from django.views import View
from netbox.views import generic
from users.models import Group
from utilities.views import ConditionalLoginRequiredMixin, ViewTab, register_model_view

from . import service
from .conf import get_setting
from .core import yaml_io
from .version import __version__

API = "plugins-api:netbox_permissions_matrix_plugin-api"
STATIC = Path(__file__).parent / "static" / "netbox_permissions_matrix_plugin"
ASSETS = ("matrix.js", "matrix.css")


@functools.lru_cache(maxsize=4)
def _assets_hash(stamps) -> str:
    digest = hashlib.sha256()
    for name in ASSETS:
        digest.update((STATIC / name).read_bytes())
    return digest.hexdigest()[:12]


def asset_version() -> str:
    """The ?v= of the plugin's JS and CSS: a hash of their contents, so browsers fetch them again whenever they change,
    also between releases. Recomputed only when a file's modification time or size changes."""
    try:
        return _assets_hash(tuple((st.st_mtime_ns, st.st_size) for st in ((STATIC / n).stat() for n in ASSETS)))
    except OSError:  # a broken install: the pages still render, cached by version as before
        return __version__


class _CheckViewMixin:
    def dispatch(self, request, *args, **kwargs):
        # Users without access get NetBox's 403 page with the reason (service.check_view raises PermissionDenied with
        # a message).
        service.check_view(request.user)
        return super().dispatch(request, *args, **kwargs)


class MatrixAccessMixin(ConditionalLoginRequiredMixin, _CheckViewMixin):
    """NetBox's login check first (anonymous users go to the login page when LOGIN_REQUIRED is set), then the
    plugin's access check."""


def api_urls() -> dict:
    return {name: reverse(f"{API}:{name}") for name in ("matrix", "principal", "plan", "apply", "import")}


class MatrixView(MatrixAccessMixin, View):
    def get(self, request):
        return render(
            request,
            "netbox_permissions_matrix_plugin/matrix.html",
            {
                # Without the action tabs the page only has the all-actions grid, whatever the URL says.
                "action": request.GET.get("action", "*") if get_setting("show_action_tabs") else "*",
                "show_tabs": get_setting("show_action_tabs"),
                "can_edit": service.can_edit(request.user),
                "api": api_urls(),
                "show_users": get_setting("show_users_by_default"),
                "asset_version": asset_version(),
                "who_can_url": reverse("plugins:netbox_permissions_matrix_plugin:who_can", args=["__ot__"]),
                "export_url": reverse("plugins:netbox_permissions_matrix_plugin:export"),
            },
        )


def _ints(values) -> tuple[int, ...]:
    return tuple(int(v) for v in values if v.isdigit())


class ExportView(MatrixAccessMixin, View):
    """The matrix as a YAML file, for the columns and rows the page shows, across every action."""

    def get(self, request):
        params = request.GET
        query = service.MatrixQuery(
            include_users=params.get("users") == "1",
            include_groups=params.get("groups") != "0",
            group_ids=_ints(params.getlist("group_id")),
            user_ids=_ints(params.getlist("user_id")),
            app_labels=tuple(a for a in params.getlist("app") if a),
        )
        doc = service.export_payload(request.user, query, params.get("q", ""))
        response = HttpResponse(yaml_io.dump(doc), content_type="application/yaml; charset=utf-8")
        filename = f"permissions-matrix-{datetime.date.today():%Y-%m-%d}.yaml"
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response


class WhoCanView(MatrixAccessMixin, View):
    def get(self, request, object_type):
        context = service.who_can(request.user, object_type)
        context["matrix_url"] = reverse("plugins:netbox_permissions_matrix_plugin:matrix")
        context["asset_version"] = asset_version()
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
            "asset_version": asset_version(),
            "who_can_url": reverse("plugins:netbox_permissions_matrix_plugin:who_can", args=["__ot__"]),
        }
