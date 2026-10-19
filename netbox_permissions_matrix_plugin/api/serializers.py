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
        if "action" not in value and "perm_id" not in value:
            raise serializers.ValidationError("Give an action or a perm_id.")
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
