from django.urls import path

from . import views

urlpatterns = [
    path("", views.MatrixView.as_view(), name="matrix"),
    path("export/", views.ExportView.as_view(), name="export"),
    path("object-types/<str:object_type>/", views.WhoCanView.as_view(), name="who_can"),
]
