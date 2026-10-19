from netbox_permissions_matrix_plugin.core.cells import CellState, cell_state, covering, inherited_state

from .factories import ALICE, NOC, OPS, perm, snapshot


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


def test_covering_is_sorted_by_id():
    snap = snapshot(perm(5, "b", ["view"], ["dcim.device"], NOC), perm(2, "a", ["view", "add"], ["dcim.device"], NOC))
    assert [p.id for p in covering(snap, NOC, "dcim.device", "view")] == [2, 5]
