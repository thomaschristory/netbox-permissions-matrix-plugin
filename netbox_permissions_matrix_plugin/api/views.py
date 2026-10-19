from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from rest_framework import status
from rest_framework.exceptions import PermissionDenied as APIPermissionDenied
from rest_framework.exceptions import ValidationError as APIValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .. import loader, service
from ..applier import apply_plan
from ..conf import get_setting
from .serializers import ChangeSetSerializer


def _ints(values):
    try:
        return tuple(int(v) for v in values)
    except ValueError as exc:
        raise APIValidationError({"detail": "IDs must be integers."}) from exc


def _bool(value, default):
    if value is None:
        return default
    return value.lower() in ("1", "true", "yes", "on")


def _change_set(request):
    object_types = {r.object_type for r in loader.rows()}
    serializer = ChangeSetSerializer(data=request.data, context={"object_types": object_types})
    serializer.is_valid(raise_exception=True)
    return serializer.validated_data


def _guard(func):
    """Turn the service's Django exceptions into API responses."""

    def wrapper(self, request, *args, **kwargs):
        try:
            return func(self, request, *args, **kwargs)
        except PermissionDenied as exc:
            raise APIPermissionDenied(str(exc)) from exc
        except ValidationError as exc:
            raise APIValidationError(exc.message_dict if hasattr(exc, "error_dict") else exc.messages) from exc

    return wrapper


class MatrixView(APIView):
    """The matrix for one action: rows, columns, cell states and the permissions behind each cell."""

    permission_classes = [IsAuthenticated]

    @_guard
    def get(self, request):
        params = request.query_params
        query = service.MatrixQuery(
            action=params.get("action", "view"),
            include_users=_bool(params.get("include_users"), get_setting("show_users_by_default")),
            group_ids=_ints(params.getlist("group_id")),
            user_ids=_ints(params.getlist("user_id")),
            app_labels=tuple(params.getlist("app_label")),
        )
        return Response(service.matrix_payload(request.user, query))


class PlanView(APIView):
    """Dry run: the operations a change set would perform, and the token to apply them with."""

    permission_classes = [IsAuthenticated]

    @_guard
    def post(self, request):
        service.check_edit(request.user)
        data = _change_set(request)
        snap, result, token = service.plan_for(request.user, data["changes"], data["edits"])
        return Response(service.plan_json(snap, result, token))


class ApplyView(APIView):
    """Apply a change set in one transaction, if nothing changed since it was planned."""

    permission_classes = [IsAuthenticated]

    @_guard
    def post(self, request):
        service.check_edit(request.user)
        data = _change_set(request)
        if not data.get("token"):
            raise APIValidationError({"token": ["Plan the change set first and send the token it returned."]})
        with transaction.atomic():
            # Lock the permission table for the plan-and-write, so two applies cannot interleave.
            loader.lock_permissions()
            snap, result, token = service.plan_for(request.user, data["changes"], data["edits"])
            if token != data["token"]:
                return Response(
                    {"detail": "The permissions changed since this plan was made. Reload and review again."},
                    status=status.HTTP_409_CONFLICT,
                )
            written = apply_plan(result, request.user)
        body = service.plan_json(snap, result, token)
        body["written"] = written
        return Response(body)
