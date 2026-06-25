from django.contrib import admin
from .models import ExecucaoScraper


@admin.register(ExecucaoScraper)
class ExecucaoScraperAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "data_inicio",
        "data_fim",
        "status",
        "total_baixados",
        "total_ja_existentes",
        "total_nao_encontrados",
    ]
    list_filter = ["status", "data_inicio"]
    search_fields = ["log_texto"]
    readonly_fields = ["data_inicio", "data_fim"]
