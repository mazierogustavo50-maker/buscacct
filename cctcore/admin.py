from django.contrib import admin
from .models import Sindicato, Empresa, EmpresaSindicato, DocumentoCCT, ConfiguracaoSistema


@admin.register(Sindicato)
class SindicatoAdmin(admin.ModelAdmin):
    list_display = ("codigo", "cnpj", "nome")
    search_fields = ("codigo", "cnpj", "nome")
    list_filter = ("codigo",)


@admin.register(Empresa)
class EmpresaAdmin(admin.ModelAdmin):
    list_display = ("codigo", "nome")
    search_fields = ("codigo", "nome")


@admin.register(EmpresaSindicato)
class EmpresaSindicatoAdmin(admin.ModelAdmin):
    list_display = ("empresa", "sindicato")
    list_filter = ("sindicato",)
    search_fields = ("empresa__nome", "sindicato__nome", "empresa__codigo", "sindicato__codigo")


@admin.register(DocumentoCCT)
class DocumentoCCTAdmin(admin.ModelAdmin):
    list_display = (
        "sindicato",
        "tipo",
        "data_inicio_vigencia",
        "data_fim_vigencia",
        "status_extracao",
        "status_analise_ia",
        "arquivo_pdf",
    )
    list_filter = ("tipo", "status_extracao", "status_analise_ia", "sindicato")
    search_fields = ("sindicato__nome", "sindicato__codigo", "arquivo_pdf")
    date_hierarchy = "data_inicio_vigencia"


@admin.register(ConfiguracaoSistema)
class ConfiguracaoSistemaAdmin(admin.ModelAdmin):
    list_display = ("chave_api_opencode", "modelo_padrao_opencode")
    
    def has_add_permission(self, request):
        # Permite apenas 1 registro
        if ConfiguracaoSistema.objects.exists():
            return False
        return super().has_add_permission(request)
