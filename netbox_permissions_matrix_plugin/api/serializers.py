from drf_spectacular.utils import extend_schema_serializer
from rest_framework import serializers

from ..core.model import UNSET, CellChange, PermEdit, PrincipalRef

ACTION = r"^[a-z_][a-z0-9_]{0,29}$"  # ObjectPermission.actions items are CharField(max_length=30)


class PrincipalSerializer(serializers.Serializer):
    type = serializers.ChoiceField(choices=["group", "user"])
    id = serializers.IntegerField(min_value=1)

    def to_internal_value(self, data):
        value = super().to_internal_value(data)
        return PrincipalRef(value["type"], value["id"])


class CellChangeSerializer(serializers.Serializer):
    principal = PrincipalSerializer()
    object_type = serializers.RegexField(r"^[a-z0-9_]+\.[a-z0-9_]+$", max_length=200)
    action = serializers.RegexField(ACTION)
    granted = serializers.BooleanField()

    def validate_object_type(self, value):
        if value not in self.context["object_types"]:
            raise serializers.ValidationError(f"{value} is not an object type permissions can be assigned to.")
        return value

    def to_internal_value(self, data):
        return CellChange(**super().to_internal_value(data))


class PermEditSerializer(serializers.Serializer):
    principal = PrincipalSerializer()
    action = serializers.RegexField(ACTION, required=False)
    perm_id = serializers.IntegerField(min_value=1, required=False)
    name = serializers.CharField(max_length=100, required=False)
    description = serializers.CharField(max_length=200, required=False, allow_blank=True)
    enabled = serializers.BooleanField(required=False)
    constraints = serializers.JSONField(required=False, allow_null=True)
    add_actions = serializers.ListField(child=serializers.RegexField(ACTION), required=False)
    add_groups = serializers.ListField(child=serializers.IntegerField(min_value=1), required=False)
    add_users = serializers.ListField(child=serializers.IntegerField(min_value=1), required=False)

    def validate_constraints(self, value):
        if value is not None and not isinstance(value, dict | list):
            raise serializers.ValidationError("Constraints must be an object, a list of objects, or null.")
        if isinstance(value, list) and not all(isinstance(c, dict) for c in value):
            raise serializers.ValidationError("A list of constraints must contain only objects.")
        return value

    def to_internal_value(self, data):
        value = super().to_internal_value(data)
        if ("action" in value) == ("perm_id" in value):
            raise serializers.ValidationError("Give either an action or a perm_id.")
        return PermEdit(
            principal=value["principal"],
            action=value.get("action", ""),
            perm_id=value.get("perm_id"),
            name=value.get("name", UNSET),
            description=value.get("description", UNSET),
            enabled=value.get("enabled", UNSET),
            constraints=value.get("constraints", UNSET),
            add_actions=tuple(value.get("add_actions", ())),
            add_groups=tuple(value.get("add_groups", ())),
            add_users=tuple(value.get("add_users", ())),
        )


class ChangeSetSerializer(serializers.Serializer):
    changes = CellChangeSerializer(many=True, required=False, default=list)
    edits = PermEditSerializer(many=True, required=False, default=list)
    token = serializers.CharField(required=False, max_length=64)


class ImportSerializer(serializers.Serializer):
    yaml = serializers.CharField(trim_whitespace=False)


# Responses. They only document the payloads (service.py and matrix.py build them); tests check that the keys match.


class NamedPrincipalSerializer(serializers.Serializer):
    type = serializers.ChoiceField(choices=["group", "user"])
    id = serializers.IntegerField()
    name = serializers.CharField(help_text="Reads 'a group you cannot view' or 'a user you cannot view' when hidden.")


class PermissionSummarySerializer(serializers.Serializer):
    id = serializers.IntegerField(allow_null=True, help_text="Null for a permission a plan would create.")
    name = serializers.CharField()
    description = serializers.CharField(allow_blank=True)
    enabled = serializers.BooleanField()
    actions = serializers.ListField(child=serializers.CharField())
    object_types = serializers.ListField(child=serializers.CharField())
    constraints = serializers.JSONField(allow_null=True)
    constrained = serializers.BooleanField()
    principals = NamedPrincipalSerializer(many=True)
    url = serializers.CharField(allow_null=True)


class ActionTabSerializer(serializers.Serializer):
    name = serializers.CharField()
    label = serializers.CharField()
    custom = serializers.BooleanField()
    freeform = serializers.BooleanField()
    help_text = serializers.CharField(allow_blank=True)


class RowSerializer(serializers.Serializer):
    object_type = serializers.CharField()
    app_label = serializers.CharField()
    app_name = serializers.CharField()
    label = serializers.CharField()
    enabled = serializers.BooleanField(required=False, help_text="For one action.")
    enabled_actions = serializers.ListField(
        child=serializers.CharField(), required=False, help_text="For every action (action=*, principal/)."
    )


class ColumnSerializer(serializers.Serializer):
    type = serializers.ChoiceField(choices=["group", "user"])
    id = serializers.IntegerField()
    key = serializers.CharField()
    name = serializers.CharField()
    simple = PermissionSummarySerializer(
        allow_null=True, required=False, help_text="For one action: the permission holding only this action."
    )
    others = PermissionSummarySerializer(
        many=True, required=False, help_text="For one action: every other permission granting it."
    )
    perms = PermissionSummarySerializer(
        many=True, required=False, help_text="For every action (action=*): every permission assigned."
    )


CELLS_HELP = (
    "By column key, then object type (then action with action=*): "
    '{"state": "granted|constrained|disabled|none", "perms": [...], "inherited": {"state": ..., "groups": [...]}}. '
    "A missing cell is none."
)


class MatrixResponseSerializer(serializers.Serializer):
    action = serializers.CharField(help_text="The action asked for, or * for every action.")
    can_edit = serializers.BooleanField()
    actions = ActionTabSerializer(many=True)
    rows = RowSerializer(many=True)
    columns = ColumnSerializer(many=True)
    cells = serializers.DictField(child=serializers.DictField(), help_text=CELLS_HELP)


class PrincipalKeySerializer(serializers.Serializer):
    type = serializers.ChoiceField(choices=["group", "user"])
    id = serializers.IntegerField()
    key = serializers.CharField()
    name = serializers.CharField()


class PrincipalResponseSerializer(serializers.Serializer):
    principal = PrincipalKeySerializer()
    can_edit = serializers.BooleanField()
    actions = ActionTabSerializer(many=True)
    rows = RowSerializer(many=True)
    columns = serializers.DictField(child=ColumnSerializer(), help_text="By action name.")
    cells = serializers.DictField(
        child=serializers.DictField(), help_text='By object type, then action: {"state": ..., "perms": [...]}.'
    )


class OperationSerializer(serializers.Serializer):
    op = serializers.ChoiceField(choices=["create", "update", "delete"])
    key = serializers.CharField()
    id = serializers.IntegerField(allow_null=True)
    before = PermissionSummarySerializer(allow_null=True)
    after = PermissionSummarySerializer(allow_null=True)
    affects = NamedPrincipalSerializer(many=True)
    reasons = serializers.ListField(child=serializers.CharField())


class PlanResponseSerializer(serializers.Serializer):
    token = serializers.CharField(help_text="Send it to apply/ with the same change set.")
    warnings = serializers.ListField(child=serializers.CharField())
    operations = OperationSerializer(many=True)


class WrittenSerializer(serializers.Serializer):
    op = serializers.ChoiceField(choices=["create", "update", "delete"])
    id = serializers.IntegerField()
    name = serializers.CharField()


class ApplyResponseSerializer(PlanResponseSerializer):
    written = WrittenSerializer(many=True)


class ImportedChangeSerializer(serializers.Serializer):
    principal = PrincipalSerializer()
    name = serializers.CharField(help_text="For display; plan/ ignores it.")
    object_type = serializers.CharField()
    action = serializers.CharField()
    granted = serializers.BooleanField()


class ImportResponseSerializer(serializers.Serializer):
    changes = ImportedChangeSerializer(many=True)
    warnings = serializers.ListField(child=serializers.CharField())
    errors = serializers.ListField(child=serializers.CharField())


class DetailSerializer(serializers.Serializer):
    detail = serializers.CharField()


# The schema's component names share one namespace with NetBox and every other plugin: prefix them.
for _cls in [c for c in tuple(globals().values()) if isinstance(c, type) and issubclass(c, serializers.Serializer)]:
    if _cls.__module__ == __name__:
        name = _cls.__name__.removesuffix("Serializer")
        extend_schema_serializer(component_name=f"PermissionsMatrix{name}")(_cls)
