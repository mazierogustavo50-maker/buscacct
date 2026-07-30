import os
from pathlib import Path

from django.contrib import admin, messages
from django.conf import settings

from .models import Sindicato, Empresa, EmpresaSindicato, EmpresaDocumentoCCT, DocumentoCCT, ConfiguracaoSistema
from .services import extrair_texto_pdf
from .management.commands.atualizar_vigencias import extrair_datas_do_texto


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


@admin.register(EmpresaDocumentoCCT)
class EmpresaDocumentoCCTAdmin(admin.ModelAdmin):
    list_display = ("empresa", "documento")
    list_filter = ("documento__sindicato",)
    search_fields = ("empresa__nome", "empresa__codigo", "documento__sindicato__nome")


@admin.register(DocumentoCCT)
class DocumentoCCTAdmin(admin.ModelAdmin):
    list_display = (
        "sindicato",
        "tipo",
        "data_inicio_vigencia",
        "data_fim_vigencia",
        "status_extracao",
        "arquivo_pdf",
    )
    list_filter = ("tipo", "status_extracao", "sindicato")
    search_fields = ("sindicato__nome", "sindicato__codigo", "arquivo_pdf")
    date_hierarchy = "data_inicio_vigencia"
    actions = ["reextrair_datas_pdf"]

    @admin.action(description="Reextrair datas dos PDFs selecionados")
    def reextrair_datas_pdf(self, request, queryset):
        atualizados = 0
        sem_mudanca = 0
        erro_pdf = 0
        total = queryset.count()

        for doc in queryset:
            caminho_pdf = doc.arquivo_pdf
            if not caminho_pdf:
                erro_pdf += 1
                continue

            if not os.path.isabs(caminho_pdf):
                caminho_pdf = str(Path(settings.BASE_DIR) / caminho_pdf)

            if not os.path.exists(caminho_pdf):
                erro_pdf += 1
                self.message_user(
                    request,
                    f"PDF não encontrado: {caminho_pdf} (doc #{doc.pk})",
                    level=messages.WARNING,
                )
                continue

            texto = extrair_texto_pdf(caminho_pdf, max_paginas=10)
            if not texto or texto.startswith("[ERRO"):
                erro_pdf += 1
                self.message_user(
                    request,
                    f"Falha ao extrair texto do PDF: {caminho_pdf} (doc #{doc.pk})",
                    level=messages.WARNING,
                )
                continue

            datas = extrair_datas_do_texto(texto)

            mudou = False
            campos_atualizar = []

            if datas["data_inicio"] and doc.data_inicio_vigencia != datas["data_inicio"]:
                doc.data_inicio_vigencia = datas["data_inicio"]
                campos_atualizar.append("data_inicio_vigencia")
                mudou = True

            if datas["data_fim"] and doc.data_fim_vigencia != datas["data_fim"]:
                doc.data_fim_vigencia = datas["data_fim"]
                campos_atualizar.append("data_fim_vigencia")
                mudou = True

            if datas["data_registro_mte"] and doc.data_registro_mte != datas["data_registro_mte"]:
                doc.data_registro_mte = datas["data_registro_mte"]
                campos_atualizar.append("data_registro_mte")
                mudou = True

            if mudou:
                doc.save(update_fields=campos_atualizar)
                atualizados += 1
            else:
                sem_mudanca += 1

        self.message_user(
            request,
            f"Reprocessamento concluído: {atualizados} atualizado(s), {sem_mudanca} sem mudança, {erro_pdf} erro(s) de {total} selecionado(s).",
            level=messages.SUCCESS if atualizados > 0 else messages.INFO,
        )


@admin.register(ConfiguracaoSistema)
class ConfiguracaoSistemaAdmin(admin.ModelAdmin):
    list_display = ("__str__",)
    
    def has_add_permission(self, request):
        # Permite apenas 1 registro
        if ConfiguracaoSistema.objects.exists():
            return False
        return super().has_add_permission(request)
