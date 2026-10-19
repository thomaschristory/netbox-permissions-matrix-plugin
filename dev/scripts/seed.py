# Sample groups, users and permissions for the dev stack: make seed. Safe to run more than once.
# Runs inside `manage.py shell`, so NetBox's apps are loaded.
from core.models import ObjectType
from users.models import Group, ObjectPermission, User


def ot(label):
    app_label, model = label.split(".")
    return ObjectType.objects.get(app_label=app_label, model=model)


groups = {name: Group.objects.get_or_create(name=name)[0] for name in ("NOC", "Ops", "Read-only", "Security")}

for username, group in (("alice", "NOC"), ("bob", "Ops"), ("carol", "Read-only"), ("dave", None)):
    user, _ = User.objects.get_or_create(username=username)
    if group:
        user.groups.add(groups[group])

PERMISSIONS = [
    # name, actions, object types, groups, users, constraints
    (
        "Read everything (DCIM, IPAM)",
        ["view"],
        ["dcim.site", "dcim.device", "dcim.rack", "ipam.prefix", "ipam.ipaddress", "ipam.vlan"],
        ["NOC", "Ops", "Read-only"],
        [],
        None,
    ),
    ("NOC-RW", ["view", "change"], ["dcim.device", "dcim.site"], ["NOC", "Ops"], [], None),
    ("Ops IPAM", ["add", "change", "delete"], ["ipam.prefix", "ipam.ipaddress"], ["Ops"], [], None),
    ("Paris devices only", ["change"], ["dcim.device"], ["Security"], [], {"site__slug": "paris"}),
    ("Own tokens", ["view", "add", "change", "delete"], ["users.token"], ["NOC", "Ops"], [], {"user": "$user"}),
    ("Old circuits access", ["view", "change"], ["circuits.circuit"], ["NOC"], [], None),
    ("Dave direct", ["view"], ["dcim.device"], [], ["dave"], None),
]

for name, actions, object_types, group_names, usernames, constraints in PERMISSIONS:
    perm, _ = ObjectPermission.objects.update_or_create(
        name=name, defaults={"actions": actions, "constraints": constraints, "enabled": name != "Old circuits access"}
    )
    perm.object_types.set([ot(label) for label in object_types])
    perm.groups.set([groups[g] for g in group_names])
    perm.users.set(User.objects.filter(username__in=usernames))

print(f"Seeded {len(groups)} groups and {len(PERMISSIONS)} permissions.")
