import os
from datetime import date
from django.core.management.base import BaseCommand
from django.core.mail import EmailMessage
from django.utils import timezone
from django.template.loader import render_to_string
from django.conf import settings
from xhtml2pdf import pisa
from io import BytesIO

from cctcore.models import DocumentoCCT, ConfiguracaoSistema, Sindicato, Empresa
from cctdashboard.views import _meses_do_desconto, MESES_RELATORIO


class Command(BaseCommand):
    help = "Gera e envia o relatório de desconto mensal por e-mail para o escritório."

    def add_arguments(self, parser):
        parser.add_argument("--mes", type=int, help="Mês do relatório (1-12). Padrão: mês atual.")
        parser.add_argument("--dry-run", action="store_true", help="Simula sem enviar e-mails.")

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        mes = options.get("mes") or date.today().month
        if not 1 <= mes <= 12:
            self.stdout.write(self.style.ERROR("Mês inválido. Use 1-12."))
            return

        config = ConfiguracaoSistema.get_config()
        emails_internos = config.emails_internos_lista()
        if not emails_internos:
            self.stdout.write(self.style.WARNING("Nenhum e-mail interno configurado. Configure em Configuração do Sistema."))
            return

        # Gera PDF do relatório de desconto mensal em memória
        documentos = list(DocumentoCCT.objects.filter(ativo=True).order_by("sindicato__nome", "-data_inicio_vigencia"))
        documentos = [d for d in documentos if mes in _meses_do_desconto(d.get_meses_desconto())]

        if not documentos:
            self.stdout.write(self.style.NOTICE(f"Nenhum sindicato com desconto no mês {MESES_RELATORIO[mes][0]}."))
            return

        sindicatos_data = []
        for doc in documentos:
            empresas = Empresa.objects.filter(sindicatos__sindicato=doc.sindicato, ativo=True).distinct().order_by("nome")
            sindicatos_data.append({
                "sindicato": doc.sindicato,
                "documento": doc,
                "empresas": empresas,
            })

        html_string = render_to_string("cctdashboard/relatorio_desconto_mensal_pdf.html", {
            "sindicatos_data": sindicatos_data,
            "mes": mes,
            "mes_nome": MESES_RELATORIO.get(mes, ("",))[0],
            "data_geracao": timezone.localtime().strftime("%d/%m/%Y %H:%M"),
        })

        pdf_buffer = BytesIO()
        pisa.CreatePDF(html_string, dest=pdf_buffer)
        pdf_buffer.seek(0)
        pdf_bytes = pdf_buffer.read()

        assunto = f"Relatório de Desconto Mensal — {MESES_RELATORIO[mes][0].title()}"
        corpo = render_to_string("emails/relatorio_escritorio.html", {
            "mes_nome": MESES_RELATORIO[mes][0],
            "total_sindicatos": len(sindicatos_data),
            "data_envio": timezone.now().strftime("%d/%m/%Y %H:%M"),
        })

        total_enviados = 0
        for email in emails_internos:
            try:
                if not dry_run:
                    msg = EmailMessage(
                        subject=assunto,
                        body=corpo,
                        from_email=settings.DEFAULT_FROM_EMAIL,
                        to=[email],
                    )
                    msg.content_subtype = "html"
                    msg.attach(f"relatorio_desconto_mensal_{mes:02d}.pdf", pdf_bytes, "application/pdf")
                    msg.send()
                self.stdout.write(self.style.SUCCESS(f"  {'[DRY-RUN] ' if dry_run else ''}Relatório enviado para <{email}>"))
                total_enviados += 1
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"  ERRO ao enviar para <{email}>: {e}"))

        self.stdout.write(self.style.NOTICE(f"\nResumo: {total_enviados} e-mail(s) enviado(s)."))
