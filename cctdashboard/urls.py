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
    # Filtro de empresas por sindicato + relatório PDF
    path("relatorio/empresas-por-sindicato/", views.filtrar_empresas_por_sindicato, name="filtro_empresas_por_sindicato"),
    path("relatorio/empresas-por-sindicato/pdf/", views.relatorio_empresas_sindicato_pdf, name="relatorio_empresas_sindicato_pdf"),
    # Documentos
    path("documentos/", views.lista_documentos, name="lista_documentos"),
    path("documentos/<int:pk>/", views.detalhe_documento, name="detalhe_documento"),
    path("documentos/<int:pk>/excluir/", views.excluir_documento, name="excluir_documento"),
    path("documentos/<int:pk>/desativar/", views.desativar_documento, name="desativar_documento"),
    path("documentos/<int:pk>/reativar/", views.reativar_documento, name="reativar_documento"),
    # PDF
    path("documentos/<int:pk>/pdf/", views.ver_pdf, name="ver_pdf"),
    # Análise IA
    path("documentos/<int:pk>/analisar-ia/", views.analisar_documento_ia, name="analisar_documento_ia"),
    # Execuções
    path("execucoes/", views.execucoes_scraper, name="execucoes_scraper"),
    path("execucoes/iniciar/", views.executar_scraper, name="executar_scraper"),
    path("execucoes/<int:pk>/", views.detalhe_execucao, name="detalhe_execucao"),
    path("execucoes/<int:pk>/abortar/", views.abortar_scraper, name="abortar_scraper"),
    path("execucoes/limpar/", views.limpar_execucoes, name="limpar_execucoes"),
    # Agendamentos
    path("agendamentos/", views.lista_agendamentos, name="lista_agendamentos"),
    path("agendamentos/novo/", views.criar_agendamento, name="criar_agendamento"),
    path("agendamentos/<int:pk>/editar/", views.editar_agendamento, name="editar_agendamento"),
    path("agendamentos/<int:pk>/excluir/", views.excluir_agendamento, name="excluir_agendamento"),
    # Relatório
    path("relatorio/", views.relatorio_execucoes, name="relatorio_execucoes"),
]
