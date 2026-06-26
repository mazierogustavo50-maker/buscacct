from django.urls import path
from . import views

app_name = "cctdashboard"

urlpatterns = [
    path("", views.home, name="home"),
    # Sindicatos
    path("sindicatos/", views.lista_sindicatos, name="lista_sindicatos"),
    path("sindicatos/novo/", views.criar_sindicato, name="criar_sindicato"),
    path("sindicatos/importar/", views.importar_sindicatos, name="importar_sindicatos"),
    path("sindicatos/<int:pk>/", views.detalhe_sindicato, name="detalhe_sindicato"),
    path("sindicatos/<int:pk>/editar/", views.editar_sindicato, name="editar_sindicato"),
    path("sindicatos/<int:pk>/excluir/", views.excluir_sindicato, name="excluir_sindicato"),
    # Empresas
    path("empresas/", views.lista_empresas, name="lista_empresas"),
    path("empresas/nova/", views.criar_empresa, name="criar_empresa"),
    path("empresas/importar/", views.importar_empresas, name="importar_empresas"),
    path("empresas/<int:pk>/", views.detalhe_empresa, name="detalhe_empresa"),
    path("empresas/<int:pk>/editar/", views.editar_empresa, name="editar_empresa"),
    path("empresas/<int:pk>/excluir/", views.excluir_empresa, name="excluir_empresa"),
    # Documentos
    path("documentos/", views.lista_documentos, name="lista_documentos"),
    path("documentos/<int:pk>/", views.detalhe_documento, name="detalhe_documento"),
    # Execuções
    path("execucoes/", views.execucoes_scraper, name="execucoes_scraper"),
    path("execucoes/iniciar/", views.executar_scraper, name="executar_scraper"),
    path("execucoes/<int:pk>/", views.detalhe_execucao, name="detalhe_execucao"),
]
