"""Every NetBox internal the plugin relies on, in one place.

NetBox's documented plugin API (netbox.plugins, netbox.views, netbox.api, utilities.views' ViewTab and
register_model_view, the models) does not say which object types a permission may hold, which custom actions models
registered, or how a constraint becomes a filter. The matrix must match NetBox's own permission form on all three, so
it reads them from NetBox's internals, here and nowhere else.

Checked against NetBox: 4.7.2, 4.7.3.

CI runs the same checks on min_version and the latest patch of each supported minor. tests_netbox/test_compat.py
fails when one of them disappears or changes shape: it must pass on a new NetBox minor before max_version is raised,
and that version added to the "Checked against" line above (tests/test_package.py keeps the line in step with
min_version and max_version).
"""

from __future__ import annotations

# Django's default permissions, which NetBox reserves (users.constants.RESERVED_ACTIONS): its plugin docs name them,
# so they are copied rather than imported. test_compat checks they still match.
RESERVED_ACTIONS = ("view", "add", "change", "delete")


def title(value) -> str:
    """str.title() that keeps existing capitals ("IP address" -> "IP Address").

    A copy of NetBox's utilities.string.title, so labels read as in NetBox's own pages. test_compat compares the two.
    """
    return " ".join(w[0].upper() + w[1:] for w in str(value).split())


def permission_object_types():
    """The object types NetBox's permission form offers, as an ObjectType queryset.

    users.constants.OBJECTPERMISSION_OBJECT_TYPES. ObjectType.objects.public() is not the same set: on NetBox 4.7.3 the
    form also offers core.managedfile, extras.scriptmodule and extras.taggeditem, and leaves out core.objecttype.
    """
    from core.models import ObjectType
    from users.constants import OBJECTPERMISSION_OBJECT_TYPES

    return ObjectType.objects.filter(OBJECTPERMISSION_OBJECT_TYPES)


def model_actions() -> dict[str, dict[str, str]]:
    """Custom actions registered by models, {"app_label.model": {action: help text}}.

    netbox.registry.registry["model_actions"] (NetBox 4.6+): filled from each model's Meta.permissions and by
    utilities.permissions.register_model_actions(). Django's own permission list holds every model's permissions,
    with no way to tell the registered ones apart, so the registry is the only source.
    """
    from netbox.registry import registry

    return {
        label: {action.name: str(action.help_text) for action in actions}
        for label, actions in registry["model_actions"].items()
    }


def constraint_filter(constraints):
    """The Q filter NetBox builds from a permission's constraints, with "$user" standing for no user (pk 0).

    utilities.permissions.qs_filter_from_constraints, as NetBox's permission form uses it to reject constraints that
    do not apply to the selected object types; "$user" is users.constants.CONSTRAINT_TOKEN_USER.
    """
    from users.constants import CONSTRAINT_TOKEN_USER
    from utilities.permissions import qs_filter_from_constraints

    return qs_filter_from_constraints(constraints, {CONSTRAINT_TOKEN_USER: 0})


def admin_menu():
    """NetBox's Admin menu and its MenuItem class, or None when NetBox no longer has them where expected.

    netbox.navigation.menu.ADMIN_MENU and netbox.navigation.MenuItem: plugins have no API for core menus, so the
    opt-in Admin placement edits that menu. Imported on each call, so tests can patch the menu.
    """
    try:
        from netbox.navigation import MenuItem
        from netbox.navigation.menu import ADMIN_MENU
    except ImportError:
        return None
    return ADMIN_MENU, MenuItem


def login_required_mixin():
    """utilities.views.ConditionalLoginRequiredMixin: NetBox's login check, which honours LOGIN_REQUIRED.

    Undocumented, but what NetBox's own views use; the alternative, Django's LoginRequiredMixin, would ignore
    LOGIN_REQUIRED = False.
    """
    from utilities.views import ConditionalLoginRequiredMixin

    return ConditionalLoginRequiredMixin
