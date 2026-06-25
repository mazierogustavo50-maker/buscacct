from django.urls import path
from . import views

app_name = "cctdashboard"

urlpatterns = [
    path("", views.home, name="home"),
    path("sindicatos/", views.lista_sindicatos, name="lista_sindicatos"),
    path("sindicatos/<int:pk>/", views.detalhe_sindicato, name="detalhe_sindicato"),
    path("empresas/", views.lista_empresas, name="lista_empresas"),
    path("empresas/<int:pk>/", views.detalhe_empresa, name="detalhe_empresa"),
    path("documentos/", views.lista_documentos, name="lista_documentos"),
    path("documentos/<int:pk>/", views.detalhe_documento, name="detalhe_documento"),
    path("execucoes/", views.execucoes_scraper, name="execucoes_scraper"),
]
