import pytest

from netbox_permissions_matrix_plugin.core.model import CellChange
from netbox_permissions_matrix_plugin.core.yaml_io import FORMAT_VERSION, dump, export_doc, import_changes, load

from .factories import ALICE, NOC, OPS, perm, snapshot

TYPES = ["dcim.device", "dcim.site", "ipam.prefix"]


def base():
    return snapshot(
        perm(1, "NOC-RW", ["view", "change"], ["dcim.device", "dcim.site"], NOC, OPS),
        perm(2, "paris", ["change"], ["ipam.prefix"], NOC, constraints={"site__slug": "paris"}),
        perm(3, "old", ["view"], ["ipam.prefix"], OPS, enabled=False),
        perm(4, "alice", ["view"], ["ipam.prefix"], ALICE),
    )


def test_export_lists_grants_constrained_and_disabled_by_name():
    doc = export_doc(base(), TYPES, [NOC, OPS, ALICE], ["view", "change"])
    assert doc["version"] == FORMAT_VERSION
    assert doc["scope"] == {
        "principals": [
            {"type": "group", "name": "NOC"},
            {"type": "group", "name": "Ops"},
            {"type": "user", "name": "alice"},
        ],
        "actions": ["view", "change"],
        "object_types": TYPES,
    }
    assert doc["grants"]["group:NOC"] == {"view": ["dcim.device", "dcim.site"], "change": ["dcim.device", "dcim.site"]}
    assert doc["grants"]["user:alice"] == {"view": ["ipam.prefix"]}
    assert doc["constrained"]["group:NOC"]["change"] == [
        {"object_type": "ipam.prefix", "permission": "paris", "constraints": {"site__slug": "paris"}}
    ]
    assert doc["disabled"]["group:Ops"]["view"] == [{"object_type": "ipam.prefix", "permission": "old"}]


def test_round_trip_is_a_noop():
    snap = base()
    doc = export_doc(snap, TYPES, [NOC, OPS, ALICE], ["view", "change"])
    changes, warnings, errors = import_changes(snap, doc, set(TYPES))
    assert (changes, warnings, errors) == ([], [], [])


def test_listed_cells_are_granted_and_unlisted_revoked_within_scope():
    snap = base()
    doc = export_doc(snap, TYPES, [NOC], ["view"])
    doc["grants"]["group:NOC"]["view"] = ["dcim.device", "ipam.prefix"]
    changes, _, errors = import_changes(snap, doc, set(TYPES))
    assert errors == []
    assert set(changes) == {
        CellChange(NOC, "ipam.prefix", "view", True),
        CellChange(NOC, "dcim.site", "view", False),
    }


def test_nothing_outside_the_scope_changes():
    snap = base()
    doc = export_doc(snap, ["dcim.device"], [NOC], ["view"])
    doc["grants"] = {}
    changes, _, _ = import_changes(snap, doc, set(TYPES))
    assert changes == [CellChange(NOC, "dcim.device", "view", False)]


def test_constrained_entry_keeps_the_cell():
    snap = base()
    doc = export_doc(snap, TYPES, [NOC], ["change"])
    changes, warnings, _ = import_changes(snap, doc, set(TYPES))
    assert changes == [] and warnings == []


def test_constrained_entry_with_nothing_on_the_target_warns():
    snap = snapshot()
    doc = export_doc(base(), TYPES, [NOC], ["change"])
    doc["grants"] = {}
    changes, warnings, _ = import_changes(snap, doc, set(TYPES))
    assert changes == []
    assert any("ipam.prefix" in w and "unchanged" in w for w in warnings)


def test_constrained_entry_granted_without_constraints_here_warns():
    # The file limits NOC's change on prefixes; the target grants it outright. The cell is kept (the import never
    # creates constraints) but the review must say the target grants more than the file.
    snap = snapshot(perm(1, "wide", ["change"], ["ipam.prefix"], NOC))
    doc = export_doc(base(), TYPES, [NOC], ["change"])
    doc["grants"] = {}
    changes, warnings, _ = import_changes(snap, doc, set(TYPES))
    assert changes == []
    assert any("ipam.prefix" in w and "without constraints" in w for w in warnings)


def test_unknown_principals_and_object_types_are_errors():
    snap = base()
    doc = {
        "version": FORMAT_VERSION,
        "scope": {
            "principals": [{"type": "group", "name": "Nobody"}, {"type": "group", "name": "NOC"}],
            "actions": ["view"],
            "object_types": ["dcim.device", "dcim.nothing"],
        },
        "grants": {"group:Nobody": {"view": ["dcim.device"]}, "group:NOC": {"view": ["dcim.device", "dcim.nothing"]}},
    }
    changes, _, errors = import_changes(snap, doc, set(TYPES))
    assert any("Nobody" in e for e in errors)
    assert any("dcim.nothing" in e for e in errors)
    assert changes == []


@pytest.mark.parametrize(
    "doc",
    [
        None,
        [],
        {"version": 99, "scope": {}},
        {"version": FORMAT_VERSION},
        {"version": FORMAT_VERSION, "scope": {"principals": "x", "actions": [], "object_types": []}},
        {"version": FORMAT_VERSION, "scope": {"principals": [], "actions": ["Bad!"], "object_types": []}},
    ],
)
def test_malformed_documents_are_errors(doc):
    changes, _, errors = import_changes(base(), doc, set(TYPES))
    assert changes == [] and errors


def test_principals_outside_visible_are_unknown_and_leak_nothing():
    # A user who may not see Ops gets the same error as for a group that does not exist, and no warning or change
    # that would reveal what Ops holds.
    snap = base()
    doc = export_doc(snap, TYPES, [NOC, OPS], ["view", "change"])
    doc["grants"] = {}
    doc["constrained"]["group:Ops"] = {"change": [{"object_type": "dcim.device", "permission": "x", "constraints": {}}]}
    changes, warnings, errors = import_changes(snap, doc, set(TYPES), visible={NOC})
    assert errors == ["Unknown group 'Ops': its entries are skipped."]
    assert all(c.principal == NOC for c in changes)
    assert not [w for w in warnings if "Ops" in w]


def test_unsupported_version_is_not_echoed_when_large():
    _, _, errors = import_changes(base(), {"version": ["x" * 10_000]}, set(TYPES))
    assert len(errors[0]) < 200


def test_dump_never_writes_anchors_and_load_round_trips():
    shared = {"site__slug": "paris"}
    doc = {"a": [shared, shared]}
    text = dump(doc)
    assert "&" not in text and "*" not in text
    assert load(text) == doc


def test_load_refuses_aliases():
    with pytest.raises(ValueError, match="aliases"):
        load("a: &x [1, 2]\nb: *x\n")


def test_load_reports_invalid_yaml_as_value_error():
    with pytest.raises(ValueError):
        load("{not: [valid")
