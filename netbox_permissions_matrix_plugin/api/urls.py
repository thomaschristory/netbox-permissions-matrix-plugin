from django.urls import path

from . import views

urlpatterns = [
    path("matrix/", views.MatrixView.as_view(), name="matrix"),
    path("principal/", views.PrincipalView.as_view(), name="principal"),
    path("plan/", views.PlanView.as_view(), name="plan"),
    path("apply/", views.ApplyView.as_view(), name="apply"),
    path("import/", views.ImportView.as_view(), name="import"),
]
