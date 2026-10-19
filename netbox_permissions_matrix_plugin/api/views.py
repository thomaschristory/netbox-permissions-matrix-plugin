import yaml
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.http import Http404
from rest_framework import status
from rest_framework.exceptions import NotFound
from rest_framework.exceptions import PermissionDenied as APIPermissionDenied
from rest_framework.exceptions import ValidationError as APIValidationError
from rest_framework.permissions import SAFE_METHODS, BasePermission, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .. import loader, service
from ..applier import apply_plan
from ..conf import get_setting
from ..core.model import PrincipalRef
from .serializers import ChangeSetSerializer, ImportSerializer


class WriteEnabled(BasePermission):
    """Refuse API tokens without write enabled on unsafe methods, as NetBox's own write endpoints do.

    NetBox's TokenWritePermission also refuses session authentication, which the matrix page uses (with CSRF).
    """

    message = "This API token is not write-enabled."

    def has_permission(self, request, view):
        token = request.auth
        return request.method in SAFE_METHODS or token is None or bool(getattr(token, "write_enabled", False))


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


class PrincipalView(APIView):
    """One group's or user's cells for every action."""

    permission_classes = [IsAuthenticated]

    @_guard
    def get(self, request):
        kind = request.query_params.get("type")
        if kind not in ("group", "user"):
            raise APIValidationError({"type": ["Must be group or user."]})
        (pk,) = _ints([request.query_params.get("id", "")]) or (0,)
        try:
            return Response(service.principal_payload(request.user, PrincipalRef(kind, pk)))
        except Http404 as exc:
            raise NotFound(str(exc)) from exc


class PlanView(APIView):
    """Dry run: the operations a change set would perform, and the token to apply them with."""

    permission_classes = [IsAuthenticated, WriteEnabled]

    @_guard
    def post(self, request):
        service.check_edit(request.user)
        data = _change_set(request)
        snap, result, token = service.plan_for(request.user, data["changes"], data["edits"])
        return Response(service.plan_json(snap, result, token))


class ApplyView(APIView):
    """Apply a change set in one transaction, if nothing changed since it was planned."""

    permission_classes = [IsAuthenticated, WriteEnabled]

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


class ImportView(APIView):
    """Read an exported YAML file and return the cell changes that would make it true. Nothing is written."""

    permission_classes = [IsAuthenticated, WriteEnabled]

    @_guard
    def post(self, request):
        service.check_edit(request.user)
        serializer = ImportSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            doc = yaml.safe_load(serializer.validated_data["yaml"])
        except yaml.YAMLError as exc:
            raise APIValidationError({"yaml": [f"Not valid YAML: {exc}"]}) from exc
        return Response(service.import_for(request.user, doc))
