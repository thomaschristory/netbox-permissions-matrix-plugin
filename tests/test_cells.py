from netbox_permissions_matrix_plugin.core.cells import CellState, cell_state, covering, inherited_state
from netbox_permissions_matrix_plugin.core.model import HIDDEN_GROUP, HIDDEN_USER

from .factories import ALICE, DAVE, NOC, OPS, RO, perm, snapshot


def test_unconstrained_enabled_grant_wins():
    snap = snapshot(
        perm(1, "constrained", ["view"], ["dcim.device"], NOC, constraints={"site__slug": "paris"}),
        perm(2, "plain", ["view"], ["dcim.device"], NOC),
    )
    assert cell_state(snap, NOC, "dcim.device", "view") is CellState.GRANTED


def test_only_constrained_grants_give_constrained():
    snap = snapshot(perm(1, "c", ["view"], ["dcim.device"], NOC, constraints=[{"site__slug": "a"}, {"status": "x"}]))
    assert cell_state(snap, NOC, "dcim.device", "view") is CellState.CONSTRAINED


def test_empty_constraints_count_as_unconstrained():
    snap = snapshot(perm(1, "c", ["view"], ["dcim.device"], NOC, constraints={}))
    assert cell_state(snap, NOC, "dcim.device", "view") is CellState.GRANTED


def test_only_disabled_grants_give_disabled():
    snap = snapshot(perm(1, "off", ["view"], ["dcim.device"], NOC, enabled=False))
    assert cell_state(snap, NOC, "dcim.device", "view") is CellState.DISABLED


def test_no_grant_gives_none():
    snap = snapshot(perm(1, "p", ["view"], ["dcim.site"], NOC), perm(2, "q", ["view"], ["dcim.device"], OPS))
    assert cell_state(snap, NOC, "dcim.device", "view") is CellState.NONE
    assert cell_state(snap, NOC, "dcim.site", "change") is CellState.NONE


def test_user_cell_ignores_group_grants():
    snap = snapshot(perm(1, "p", ["view"], ["dcim.device"], NOC))
    assert cell_state(snap, ALICE, "dcim.device", "view") is CellState.NONE


def test_inherited_state_names_the_groups():
    snap = snapshot(perm(1, "p", ["view"], ["dcim.device"], NOC))
    assert inherited_state(snap, ALICE.id, "dcim.device", "view") == (CellState.GRANTED, ["NOC"])
    assert inherited_state(snap, ALICE.id, "dcim.site", "view") == (CellState.NONE, [])


def test_hiding_leaves_out_the_names_of_hidden_principals():
    snap = snapshot(perm(1, "p", ["view"], ["dcim.device"], NOC, OPS, ALICE, DAVE)).hiding({NOC, ALICE})
    assert [snap.name_of(r) for r in (NOC, OPS, RO, ALICE, DAVE)] == [
        "NOC",
        HIDDEN_GROUP,
        HIDDEN_GROUP,
        "alice",
        HIDDEN_USER,
    ]
    assert snap.covering_ids(OPS, "dcim.device", "view") == [1]


def test_inherited_state_does_not_name_hidden_groups():
    snap = snapshot(
        perm(1, "noc", ["view"], ["dcim.device"], NOC),
        perm(2, "ops", ["view"], ["dcim.device"], OPS, constraints={"site__slug": "paris"}),
        perm(3, "ro", ["view"], ["dcim.device"], RO),
        memberships={ALICE.id: frozenset({NOC.id, OPS.id, RO.id})},
    ).hiding({NOC})
    # Hidden groups come last, as one marker: the viewer learns there is access it cannot see, not how many groups.
    assert inherited_state(snap, ALICE.id, "dcim.device", "view") == (CellState.GRANTED, ["NOC", HIDDEN_GROUP])
    assert inherited_state(snap.hiding(set()), ALICE.id, "dcim.device", "view") == (CellState.GRANTED, [HIDDEN_GROUP])


def test_covering_is_sorted_by_id():
    snap = snapshot(perm(5, "b", ["view"], ["dcim.device"], NOC), perm(2, "a", ["view", "add"], ["dcim.device"], NOC))
    assert [p.id for p in covering(snap, NOC, "dcim.device", "view")] == [2, 5]
