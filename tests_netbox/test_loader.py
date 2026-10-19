from django.test import TestCase

from netbox_permissions_matrix_plugin import loader
from netbox_permissions_matrix_plugin.core.model import GROUP, USER, PrincipalRef

from .fixtures import groups, make_perm, user


class LoadSnapshotTest(TestCase):
    def setUp(self):
        self.noc, self.ops = groups("NOC", "Ops")
        self.alice = user("alice", self.noc)
        self.perm = make_perm(
            "NOC-RW", ["view", "change"], ["dcim.device", "dcim.site"], groups=[self.noc, self.ops], users=[self.alice]
        )

    def test_snapshot_contains_permissions_as_plain_data(self):
        snap = loader.load_snapshot()
        perm = snap.perms[self.perm.pk]
        self.assertEqual(perm.name, "NOC-RW")
        self.assertEqual(perm.actions, ("view", "change"))
        self.assertEqual(perm.object_types, {"dcim.device", "dcim.site"})
        self.assertEqual(perm.groups, {self.noc.pk, self.ops.pk})
        self.assertEqual(perm.users, {self.alice.pk})

    def test_snapshot_names_principals_and_memberships(self):
        snap = loader.load_snapshot()
        self.assertEqual(snap.name_of(PrincipalRef(GROUP, self.noc.pk)), "NOC")
        self.assertEqual(snap.name_of(PrincipalRef(USER, self.alice.pk)), "alice")
        self.assertEqual(snap.memberships[self.alice.pk], {self.noc.pk})

    def test_snapshot_query_count_does_not_grow_with_permissions(self):
        loader.load_snapshot()
        with self.assertNumQueries(loader.SNAPSHOT_QUERIES):
            loader.load_snapshot()
        for i in range(10):
            make_perm(f"p{i}", ["view"], ["dcim.rack"], groups=[self.ops])
        with self.assertNumQueries(loader.SNAPSHOT_QUERIES):
            loader.load_snapshot()


class RowsTest(TestCase):
    def test_rows_are_permission_object_types_grouped_by_app(self):
        rows = loader.rows()
        labels = [r.object_type for r in rows]
        self.assertIn("dcim.device", labels)
        self.assertIn("extras.taggeditem", labels)
        self.assertNotIn("core.objecttype", labels)
        device = next(r for r in rows if r.object_type == "dcim.device")
        self.assertEqual(device.app_label, "dcim")
        self.assertEqual(device.app_name, "DCIM")
        self.assertEqual(device.label, "Device")
        self.assertEqual(labels, sorted(labels, key=lambda ot: (ot.split(".")[0], ot)))

    def test_hidden_apps_have_no_rows(self):
        labels = {r.object_type for r in loader.rows(hidden_apps=["wireless"])}
        self.assertFalse(any(label.startswith("wireless.") for label in labels))

    def test_custom_actions_registered_by_models(self):
        # NetBox 4.6+ registers "sync" on data sources and "render_config" on devices, among others.
        rows = {r.object_type: r for r in loader.rows()}
        registered = set().union(*(r.custom_actions for r in rows.values()))
        self.assertTrue(registered)


class ActionTabsTest(TestCase):
    def test_tabs_list_crud_then_registered_then_freeform(self):
        make_perm("odd", ["view", "frobnicate"], ["dcim.site"])
        tabs = loader.action_tabs(loader.load_snapshot(), loader.rows())
        names = [t.name for t in tabs]
        self.assertEqual(names[:4], ["view", "add", "change", "delete"])
        self.assertEqual(names[-1], "frobnicate")
        self.assertTrue(tabs[-1].freeform)
        self.assertTrue(all(t.custom for t in tabs[4:-1]))
