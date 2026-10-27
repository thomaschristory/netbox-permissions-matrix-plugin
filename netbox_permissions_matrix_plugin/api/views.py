from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.http import Http404
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from netbox.api.authentication import TokenWritePermission
from rest_framework import status
from rest_framework.exceptions import NotFound
from rest_framework.exceptions import PermissionDenied as APIPermissionDenied
from rest_framework.exceptions import ValidationError as APIValidationError
from rest_framework.permissions import SAFE_METHODS, BasePermission, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from users.models import Token

from .. import loader, service
from ..applier import apply_plan
from ..conf import get_setting
from ..core import yaml_io
from ..core.model import PrincipalRef
from .serializers import (
    ApplyResponseSerializer,
    ChangeSetSerializer,
    DetailSerializer,
    ImportResponseSerializer,
    ImportSerializer,
    MatrixResponseSerializer,
    PlanResponseSerializer,
    PrincipalResponseSerializer,
)


class WriteEnabled(BasePermission):
    """NetBox's TokenWritePermission for token requests: unsafe methods need a write-enabled token.

    TokenWritePermission refuses session authentication outright, and the matrix page uses sessions (with CSRF), so
    those are let through here; the views still check the user's permissions.
    """

    message = "This API token is not write-enabled."

    def has_permission(self, request, view):
        if isinstance(request.auth, Token):
            return TokenWritePermission().has_permission(request, view)
        return request.method in SAFE_METHODS or request.auth is None


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


ERRORS = {
    400: OpenApiResponse(OpenApiTypes.OBJECT, description="Invalid request."),
    403: OpenApiResponse(DetailSerializer, description="Not allowed."),
}
WRITE_ERRORS = {
    **ERRORS,
    403: OpenApiResponse(DetailSerializer, description="Not allowed, or the token is not write-enabled."),
}


class MatrixView(APIView):
    """The matrix for one action: rows, columns, cell states and the permissions behind each cell."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        parameters=[
            OpenApiParameter("action", str, description="An action name, or * for every action. Default: view."),
            OpenApiParameter("include_users", bool, description="Add a column per user with direct permissions."),
            OpenApiParameter("group_id", int, many=True, description="Only these groups."),
            OpenApiParameter("user_id", int, many=True, description="These users (implies user columns)."),
            OpenApiParameter("app_label", str, many=True, description="Only rows of these apps."),
        ],
        responses={200: MatrixResponseSerializer, **ERRORS},
    )
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

    @extend_schema(
        parameters=[
            OpenApiParameter("type", str, required=True, enum=["group", "user"]),
            OpenApiParameter("id", int, required=True, description="The group's or user's ID."),
        ],
        responses={
            200: PrincipalResponseSerializer,
            404: OpenApiResponse(DetailSerializer, description="Unknown, or not visible to you."),
            **ERRORS,
        },
    )
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

    @extend_schema(
        request=ChangeSetSerializer,
        responses={200: PlanResponseSerializer, **WRITE_ERRORS},
    )
    @_guard
    def post(self, request):
        service.check_edit(request.user)
        data = _change_set(request)
        snap, result, token = service.plan_for(request.user, data["changes"], data["edits"])
        return Response(service.plan_json(snap, result, token))


def _conflict(detail):
    return Response({"detail": detail}, status=status.HTTP_409_CONFLICT)


class ApplyView(APIView):
    """Apply a change set in one transaction, if nothing changed since it was planned."""

    permission_classes = [IsAuthenticated, WriteEnabled]

    @extend_schema(
        request=ChangeSetSerializer,
        responses={
            200: ApplyResponseSerializer,
            409: OpenApiResponse(DetailSerializer, description="The permissions changed since the plan. Plan again."),
            **WRITE_ERRORS,
        },
    )
    @_guard
    def post(self, request):
        service.check_edit(request.user)
        data = _change_set(request)
        if not data.get("token"):
            raise APIValidationError({"token": ["Plan the change set first and send the token it returned."]})
        try:
            with transaction.atomic():
                # Lock the permission table for the plan-and-write, so two applies cannot interleave.
                loader.lock_permissions()
                snap, result, token = service.plan_for(request.user, data["changes"], data["edits"])
                if token != data["token"]:
                    return _conflict("The permissions changed since this plan was made. Reload and review again.")
                written = apply_plan(result, request.user)
        except IntegrityError:
            # A group or user of the plan was deleted while it was written. The transaction is rolled back.
            return _conflict("A group or user in this plan was deleted while it was applied. Reload and review again.")
        body = service.plan_json(snap, result, token)
        body["written"] = written
        return Response(body)


class ImportView(APIView):
    """Read an exported YAML file and return the cell changes that would make it true. Nothing is written."""

    permission_classes = [IsAuthenticated, WriteEnabled]

    @extend_schema(
        request=ImportSerializer,
        responses={200: ImportResponseSerializer, **WRITE_ERRORS},
    )
    @_guard
    def post(self, request):
        service.check_edit(request.user)
        serializer = ImportSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            doc = yaml_io.load(serializer.validated_data["yaml"])
        except ValueError as exc:
            raise APIValidationError({"yaml": [str(exc)]}) from exc
        return Response(service.import_for(request.user, doc))
