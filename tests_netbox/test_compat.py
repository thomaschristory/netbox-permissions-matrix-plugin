"""The NetBox internals compat.py relies on: these fail when a NetBox release removes one or changes its shape."""

from django.db.models import Q
from django.test import SimpleTestCase, TestCase

from netbox_permissions_matrix_plugin import compat, loader


class ConstantsTest(SimpleTestCase):
    def test_reserved_actions_match_netbox(self):
        from users.constants import RESERVED_ACTIONS

        self.assertEqual(compat.RESERVED_ACTIONS, tuple(RESERVED_ACTIONS))

    def test_title_matches_netbox(self):
        from utilities.string import title

        for value in ("device", "IP address", "VM interface", "render_config", "  two  spaces ", ""):
            self.assertEqual(compat.title(value), title(value), value)


class PermissionObjectTypesTest(TestCase):
    def test_netbox_filter_is_a_q(self):
        from users.constants import OBJECTPERMISSION_OBJECT_TYPES

        self.assertIsInstance(OBJECTPERMISSION_OBJECT_TYPES, Q)

    def test_same_rows_as_the_permission_form(self):
        # The form's object type choices, by app: the matrix rows must be the same types, with the same labels.
        from core.models import ObjectType
        from users.forms.model_forms import get_object_types_choices

        choices = [(pk, str(label)) for _, app_choices in get_object_types_choices() for pk, label in app_choices]
        self.assertEqual({ot.pk for ot in compat.permission_object_types()}, {pk for pk, _ in choices})
        names = {ot.pk: f"{ot.app_label}.{ot.model}" for ot in ObjectType.objects.all()}
        self.assertEqual({(r.object_type, r.label) for r in loader.rows()}, {(names[pk], lb) for pk, lb in choices})

    def test_differs_from_public_object_types(self):
        # Why the plugin does not use ObjectType.objects.public(): if this fails, NetBox made them the same set and
        # compat.permission_object_types() can switch to the public API.
        from core.models import ObjectType

        labels = {f"{ot.app_label}.{ot.model}" for ot in compat.permission_object_types()}
        public = {f"{ot.app_label}.{ot.model}" for ot in ObjectType.objects.public()}
        self.assertNotEqual(labels, public)
        self.assertIn("extras.taggeditem", labels - public)
        self.assertIn("core.objecttype", public - labels)


class ModelActionsTest(SimpleTestCase):
    def test_registry_shape(self):
        from netbox.registry import registry

        self.assertIn("model_actions", registry)
        for label, actions in registry["model_actions"].items():
            self.assertRegex(label, r"^\w+\.\w+$")
            for action in actions:
                self.assertIsInstance(action.name, str)
                self.assertTrue(hasattr(action, "help_text"), action)

    def test_registered_actions(self):
        # NetBox registers these from Meta.permissions; the plugin lists them as custom actions.
        actions = compat.model_actions()
        self.assertIn("sync", actions["core.datasource"])
        self.assertIn("render_config", actions["dcim.device"])
        self.assertTrue(all(isinstance(h, str) for a in actions.values() for h in a.values()))
        self.assertFalse(set(compat.RESERVED_ACTIONS) & {n for a in actions.values() for n in a})


class ConstraintFilterTest(TestCase):
    def test_builds_the_filter_netbox_enforces(self):
        from dcim.models import Site

        site = Site.objects.create(name="a", slug="a")
        Site.objects.create(name="b", slug="b")
        self.assertEqual(list(Site.objects.filter(compat.constraint_filter([{"slug": "a"}]))), [site])
        self.assertEqual(Site.objects.filter(compat.constraint_filter([{"slug": "a"}, {}])).count(), 2)

    def test_user_token_stands_for_no_user(self):
        from users.constants import CONSTRAINT_TOKEN_USER

        self.assertEqual(CONSTRAINT_TOKEN_USER, "$user")
        self.assertEqual(compat.constraint_filter([{"created_by": "$user"}]), Q(created_by=0))
        self.assertEqual(compat.constraint_filter([{"id__in": ["$user", 3]}]), Q(id__in=[0, 3]))

    def test_bad_field_raises(self):
        from dcim.models import Site
        from django.core.exceptions import FieldError

        with self.assertRaises(FieldError):
            Site.objects.filter(compat.constraint_filter([{"nope": 1}])).exists()


class AdminMenuTest(SimpleTestCase):
    def test_menu_and_item_class_are_found(self):
        found = compat.admin_menu()
        self.assertIsNotNone(found, "netbox.navigation.MenuItem or netbox.navigation.menu.ADMIN_MENU moved")
        menu, item_class = found
        links = [item.link for group in menu.groups for item in group.items]
        self.assertIn("users:objectpermission_list", links)
        item_class(link="users:objectpermission_list", link_text="x", permissions=[])


class LoginRequiredMixinTest(SimpleTestCase):
    def test_is_netbox_mixin(self):
        from django.contrib.auth.mixins import AccessMixin

        mixin = compat.login_required_mixin()
        self.assertTrue(issubclass(mixin, AccessMixin))
        self.assertTrue(hasattr(mixin, "dispatch"))
